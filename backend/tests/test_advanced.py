"""P4–P5: Policy Lab, Simulator, Replay, Graph, Drift, Regulatory impact, scans, brief, evidence requests, workspaces."""
from sqlalchemy import select

from app.database.session import SessionLocal
from app.models import Control, Evidence, EvidenceRequest, Notification
from tests.conftest import as_role, wait_run

CO = "COMPLIANCE_OFFICER"


def _control(code):
    with SessionLocal() as db:
        return db.execute(select(Control).where(Control.company_id == 1, Control.code == code)).scalar_one()


def test_policy_lab_simulates_without_saving(client):
    before = _control("C-019").frequency_days
    r = client.post("/api/policies/simulate-change", json={"policy_code": "POL-002", "proposed_interval_days": 60}, headers=as_role(client, CO)).json()
    assert r["summary"].startswith("Policy change would affect") and len(r["affected_controls"]) >= 5
    assert any(c["becomes_overdue"] for c in r["affected_controls"]) and r["testing_impact"]["extra_tests_per_year"] > 0
    assert _control("C-019").frequency_days == before  # nothing persisted


def test_policy_lab_requires_permission(client):
    r = client.post("/api/policies/simulate-change", json={"policy_code": "POL-002", "proposed_interval_days": 60}, headers=as_role(client, "AUDITOR"))
    assert r.status_code == 403 and r.json()["detail"]["why"]["required_permission"] == "POLICIES_MANAGE"


def test_simulator_what_if_control_fails(client):
    r = client.post("/api/simulate/control", json={"control_code": "C-042", "test_result": "FAIL", "evidence_state": "EXPIRED"},
                    headers=as_role(client, CO)).json()
    assert r["status"] == {"before": "PASS", "after": "FAIL"}
    assert r["risk"]["after"]["score"] > r["risk"]["before"]["score"] and r["readiness"]["after"] < r["readiness"]["before"]
    assert r["potential_finding"] and r["recommended_remediation"] and r["affected_requirements"]
    with SessionLocal() as db:  # evidence untouched
        ev = db.execute(select(Evidence).where(Evidence.control_id == _control("C-042").id, Evidence.is_current.is_(True))).scalars().all()
        from app.compliance.snapshot import evidence_status
        assert all(evidence_status(e) != "EXPIRED" for e in ev)


def test_simulator_access_review_needs_high_approval(client):
    r = client.post("/api/simulate/control", json={"control_code": "C-017", "test_result": "FAIL"}, headers=as_role(client, CO)).json()
    assert r["required_approval"]["risk_level"] == "HIGH" and r["potential_finding"]["would_recur"]


def test_audit_replay(client):
    audits = client.get("/api/audits", headers=as_role(client, "AUDITOR")).json()
    iso = next(a for a in audits if a["code"] == "AUD-ISO-2025")
    r = client.get(f"/api/audits/{iso['id']}/replay", headers=as_role(client, "AUDITOR")).json()
    kinds = [f["kind"] for f in r["frames"]]
    assert kinds[:4] == ["scope", "tests", "evidence", "findings"] and "verification" in kinds and kinds[-1] == "result"
    assert r["stats"]["findings"] == 9


def test_compliance_graph_focus(client):
    g = client.get("/api/graph?focus=C-017", headers=as_role(client, CO)).json()
    kinds = {n["kind"] for n in g["nodes"]}
    assert {"requirement", "control", "evidence", "test", "finding", "remediation", "verification"} <= kinds
    ids = {n["id"] for n in g["nodes"]}
    assert all(e["from"] in ids and e["to"] in ids for e in g["edges"])


def test_control_drift(client):
    d = client.get("/api/drift", headers=as_role(client, CO)).json()
    by = {x["control"]["code"]: [s["type"] for s in x["signals"]] for x in d}
    assert "Requirement changed" in by["C-055"] and "C-031" in by


def test_regulatory_impact(client):
    ch = next(c for c in client.get("/api/regulatory-changes", headers=as_role(client, CO)).json() if c["code"] == "RC-001")
    r = client.post("/api/regulatory-changes/analyze", json={"change_id": ch["id"]}, headers=as_role(client, CO)).json()
    assert r["misaligned_controls"] == ["C-055"] and r["new_risk"] in ("HIGH", "CRITICAL")
    assert any(t["op"] == "add" for t in r["diff"]) and r["upcoming_audits"]


def test_scan_runs_and_deduplicates_alerts(client):
    h = as_role(client, CO)
    first = client.post("/api/scans/run", headers=h).json()
    second = client.post("/api/scans/run", headers=h).json()
    assert first["alerts"] == second["alerts"] > 0
    assert second["notifications_sent"] == 0  # duplicates within 24h suppressed
    hist = client.get("/api/scans", headers=h).json()["history"]
    assert len(hist) >= 3 and hist[0]["summary"]["readiness"] == 78


def test_morning_brief_scoped_for_control_owner(client):
    b = client.get("/api/brief", headers=as_role(client, CO)).json()
    assert b["top_priority"]["code"] == "C-017" and b["scope"] == "NovaTech"
    mine = client.get("/api/brief", headers=as_role(client, "CONTROL_OWNER")).json()
    assert mine["scope"] == "your controls"


def test_evidence_request_workflow(client):
    h = as_role(client, CO)
    c31 = _control("C-031")
    r = client.post("/api/evidence-requests", json={"control_id": c31.id, "evidence_required": "Vendor SOC report",
                                                   "reason": "Missing evidence", "due_date": "2099-01-01"}, headers=h).json()
    assert r["status"] == "OPEN" and r["delivery"] == "Demo Notification"
    with SessionLocal() as db:
        assert db.execute(select(Notification).where(Notification.title.like("Evidence requested: C-031%"))).scalars().first()
    up = client.post("/api/evidence", data={"control_id": str(c31.id), "name": "Vendor SOC report 2026", "valid_days": "180"},
                     files={"file": ("vendor_soc.txt", b"Vendor SOC 2 report summary. No exceptions noted.", "text/plain")}, headers=h).json()
    assert r["code"] in up["fulfilled_requests"]
    with SessionLocal() as db:
        assert db.execute(select(EvidenceRequest).where(EvidenceRequest.code == r["code"])).scalar_one().status == "FULFILLED"
    import tests.conftest as cf

    cf.reseed()  # the upload changed C-031's evidence; restore the demo baseline for later tests
    cf._tokens.clear()


def test_control_owner_workspace(client):
    w = client.get("/api/workspace/me", headers=as_role(client, "CONTROL_OWNER")).json()
    assert {c["code"] for c in w["controls"]} >= {"C-017"} and any(r["control"]["code"] == "C-017" for r in w["evidence_requests"])


def test_observability(client):
    o = client.get("/api/observability", headers=as_role(client, CO)).json()
    assert o["kpis"]["agent_runs"] >= 1 and o["cost_label"] == "Prototype estimate"


def test_agent_simulation_and_brief_intents(client):
    h = as_role(client, CO)
    for q, intent, card in [("What happens if C-024 fails?", "simulate_control", "simulation"),
                            ("Give me my morning brief", "morning_brief", "brief"),
                            ("What if access reviews were every 60 days?", "policy_lab", "policy_simulation")]:
        run = wait_run(client, h, client.post("/api/agent/chat", json={"message": q}, headers=h).json()["id"])
        assert run["intent"] == intent and run["status"] == "COMPLETED", run["content"]
        assert any(c["type"] == card for c in run["cards"])

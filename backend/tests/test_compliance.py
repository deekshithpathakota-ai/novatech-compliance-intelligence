"""Compliance engines, agent workflow and the end-to-end remediation / approval / verification loop."""
from sqlalchemy import select

from app.compliance.gaps import detect_gaps
from app.compliance.readiness import posture
from app.compliance.snapshot import load_snapshot, next_upcoming_audit
from app.database.session import SessionLocal
from app.models import Company, MemoryRecord, VerificationRecord
from app.risk.engine import DEFAULT_RISK_CONFIG, assess_control, merged_config
from tests.conftest import as_role, reseed, wait_run

CO = "COMPLIANCE_OFFICER"


def _scope():
    db = SessionLocal()
    a = next_upcoming_audit(db, 1)
    return db, load_snapshot(db, 1, audit_id=a.id)


def test_dashboard_numbers_are_computed(client):
    d = client.get("/api/dashboard", headers=as_role(client, CO)).json()
    m = d["metrics"]
    assert (m["readiness"], m["open_findings"], m["critical_risks"], m["evidence_expiring"]) == (78, 7, 2, 6)


def test_risk_engine_categories():
    db, snap = _scope()
    assert assess_control(snap.by_code("C-017")).category == "HIGH"
    assert assess_control(snap.by_code("C-018")).category == "CRITICAL"
    assert assess_control(snap.by_code("C-042")).category == "LOW"
    db.close()


def test_risk_engine_is_configurable():
    db, snap = _scope()
    cfg = merged_config({"risk_model": {"thresholds": {"CRITICAL": 95, "HIGH": 80, "MEDIUM": 50}}})
    assert assess_control(snap.by_code("C-018"), cfg).category == "HIGH"
    assert assess_control(snap.by_code("C-018"), DEFAULT_RISK_CONFIG).category == "CRITICAL"
    db.close()


def test_control_status_and_evidence():
    db, snap = _scope()
    c17 = snap.by_code("C-017")
    assert c17.status == "OVERDUE" and c17.days_since_test == 142 and c17.evidence_state == "EXPIRED"
    assert snap.by_code("C-042").status == "PASS"
    assert snap.by_code("C-031").evidence_state == "MISSING"
    db.close()


def test_gap_detection_scope():
    db, snap = _scope()
    g = detect_gaps(snap)
    assert g["gap_count"] == 7 and g["expiring_evidence"] == 6
    assert {s["subject_code"] for s in g["subjects"]} == {"C-017", "C-018", "C-024", "C-031", "C-055", "C-063", "ISO-8.11"}
    types = {x["type"] for x in g["gaps"]}
    assert {"REQUIREMENT_UNMAPPED", "RECURRING_FINDING", "CONTROL_MISALIGNED", "CONFLICTING_EVIDENCE"} <= types
    db.close()


def test_recurring_findings(client):
    rec = client.get("/api/findings/recurring", headers=as_role(client, CO)).json()
    by = {r["control_code"]: r for r in rec}
    assert set(by) == {"C-017", "C-031"}
    assert by["C-017"]["occurrences"] == 3 and by["C-017"]["effectiveness"]["level"] == "LOW"
    assert any(h["factor"] == "Remediation was temporary" for h in by["C-017"]["hypotheses"])


def test_readiness_indicators_labelled():
    db, snap = _scope()
    p = posture(snap)
    assert p["readiness"]["label"] == "NovaTech Compliance Readiness Indicators"
    assert "not an official certification" in p["readiness"]["disclaimer"]
    db.close()


def test_explain_control_why(client):
    r = client.get("/api/explain", params={"kind": "control", "code": "C-017"}, headers=as_role(client, CO)).json()
    assert "high risk" in r["title"] and any(pt["label"] == "Recurrence" for pt in r["points"])


def test_control_test_uses_evidence(client):
    h = as_role(client, CO)
    c42 = next(c for c in client.get("/api/controls", headers=h).json() if c["code"] == "C-042")
    out = client.post(f"/api/controls/{c42['id']}/test", headers=h).json()
    assert out["result"] == "PASS" and all(q["answer"] == "Yes" for q in out["questions"])


def test_agent_readiness_workflow(client):
    h = as_role(client, CO)
    run = client.post("/api/agent/chat", json={"message": "Prepare NovaTech for our upcoming ISO 27001-style audit."}, headers=h).json()
    r = wait_run(client, h, run["id"])
    assert r["status"] == "COMPLETED" and r["intent"] == "audit_readiness"
    metrics = {i["label"]: i["value"] for i in next(c for c in r["cards"] if c["type"] == "summary_metrics")["items"]}
    assert metrics["Potential gaps"] == 7 and metrics["Recurring findings"] == 2 and metrics["High-risk controls"] == 2
    steps = client.get(f"/api/agent/runs/{run['id']}/steps", headers=h).json()
    events = {s["event"] for s in steps["steps"]}
    assert {"agent.started", "plan.created", "finding.detected", "memory.updated", "agent.completed"} <= events
    assert all(t["authorized"] for t in steps["tool_calls"])


def test_close_without_verification_is_blocked(client):
    h = as_role(client, CO)
    f = next(x for x in client.get("/api/findings", headers=h).json() if x["code"] == "FND-2026-043")
    assert client.post(f"/api/findings/{f['id']}/close", headers=h).status_code == 409


def test_auditor_cannot_approve(client):
    h = as_role(client, "AUDITOR")
    ap = next(a for a in client.get("/api/approvals", headers=h).json() if a["status"] == "PENDING")
    assert client.post(f"/api/approvals/{ap['id']}/approve", json={}, headers=h).status_code == 403


def test_hero_remediation_approval_verification_memory(client):
    """Full loop: plan -> approval -> action -> verification -> status -> memory -> close -> report."""
    h = as_role(client, CO)
    f = next(x for x in client.get("/api/findings", headers=h).json() if x["code"] == "FND-2026-041")
    run = client.post(f"/api/findings/{f['id']}/remediation", headers=h).json()
    r = wait_run(client, h, run["id"])
    assert r["status"] == "AWAITING_APPROVAL"
    ap = next(c for c in r["cards"] if c["type"] == "approval")["approval"]
    assert ap["risk_level"] == "HIGH" and ap["affected"]["accounts"] == 17
    res = client.post(f"/api/approvals/{ap['id']}/approve", json={"note": "ok"}, headers=h).json()
    r2 = wait_run(client, h, res["run"]["id"])
    assert r2["status"] == "COMPLETED", r2["content"]
    ver = next(c for c in r2["cards"] if c["type"] == "verification")
    assert ver["before"] == 17 and ver["after"] == 0 and ver["result"] == "PASSED"
    c17 = client.get(f"/api/controls/{f['control_id']}", headers=h).json()
    assert c17["status"] == "PASS" and c17["evidence_status"] == "VALID"
    with SessionLocal() as db:
        assert db.execute(select(VerificationRecord).where(VerificationRecord.finding_id == f["id"], VerificationRecord.result == "PASSED")).scalars().first()
        assert db.execute(select(MemoryRecord).where(MemoryRecord.subject_code == "C-017", MemoryRecord.category == "VERIFICATION",
                                                     MemoryRecord.written_by == "agent")).scalars().first()
    assert client.post(f"/api/findings/{f['id']}/close", headers=h).json()["status"] == "CLOSED"
    d = client.get("/api/dashboard", headers=h).json()["metrics"]
    assert d["open_findings"] == 6 and d["readiness"] > 78
    rep = client.post("/api/reports/audit-readiness", headers=h).json()
    pdf = client.get(f"/api/reports/{rep['id']}/pdf", headers=h)
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"


def test_verification_fails_safe_when_evidence_source_down(client):
    """Self-recovery: retries, then INCONCLUSIVE — never claims success."""
    reseed()
    import tests.conftest as cf

    cf._tokens.clear()
    h = as_role(client, CO)
    with SessionLocal() as db:
        c = db.get(Company, 1)
        c.settings = {**c.settings, "fault_injection": {"evidence_store": True}}
        db.commit()
    f = next(x for x in client.get("/api/findings", headers=h).json() if x["code"] == "FND-2026-041")
    r = wait_run(client, h, client.post(f"/api/findings/{f['id']}/remediation", headers=h).json()["id"])
    ap = next(c for c in r["cards"] if c["type"] == "approval")["approval"]
    r2 = wait_run(client, h, client.post(f"/api/approvals/{ap['id']}/approve", json={}, headers=h).json()["run"]["id"])
    assert r2["status"] == "FAILED"
    assert "evidence source was unavailable" in r2["content"]
    fd = client.get(f"/api/findings/{f['id']}", headers=h).json()
    assert fd["status"] == "IN_REMEDIATION" and not fd["can_close"]
    reseed()
    cf._tokens.clear()

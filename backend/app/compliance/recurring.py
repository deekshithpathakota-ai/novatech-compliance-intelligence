"""Recurring finding detection, remediation effectiveness and rule-based root-cause hypotheses."""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

from app.compliance.snapshot import OPEN_FINDING_STATUSES, ControlView, Snapshot, _aware

HYPOTHESIS_LABEL = "AI-generated hypotheses requiring human validation"


def _occurrence(f, snap: Snapshot) -> dict:
    plans = [p for p in snap.plans if p.finding_id == f.id]
    vers = [v for v in snap.verifications if v.finding_id == f.id]
    audit = next((a for a in snap.audits if a.id == f.audit_id), None)
    return {
        "finding_code": f.code, "finding_id": f.id, "title": f.title, "severity": f.severity, "status": f.status,
        "detected_at": _aware(f.detected_at).date().isoformat(),
        "closed_at": _aware(f.closed_at).date().isoformat() if f.closed_at else None,
        "audit": {"code": audit.code, "name": audit.name, "id": audit.id} if audit else None,
        "remediation": [{"code": p.code, "title": p.title, "status": p.status,
                         "summary": p.summary_of_actions} for p in plans],
        "verification": [{"code": v.code, "result": v.result, "at": _aware(v.verified_at).date().isoformat()}
                         for v in sorted(vers, key=lambda v: _aware(v.verified_at))],
        "root_cause": f.root_cause,
    }


def effectiveness(occurrences: list[dict]) -> dict:
    """Completed? Verified? Recurred? -> LOW / MEDIUM / HIGH."""
    closed = [o for o in occurrences if o["status"] == "CLOSED"]
    verified_pass = sum(1 for o in occurrences for v in o["verification"] if v["result"] == "PASSED")
    verified_fail = sum(1 for o in occurrences for v in o["verification"] if v["result"] == "FAILED")
    recurred_after_fix = len(occurrences) > 1 and any(o["remediation"] for o in occurrences[:-1])
    if recurred_after_fix and len(occurrences) >= 3:
        level = "LOW"
    elif recurred_after_fix:
        level = "MEDIUM"
    else:
        level = "HIGH"
    return {"level": level, "remediations_completed": len(closed), "verifications_passed": verified_pass,
            "verifications_failed": verified_fail, "recurred_after_remediation": recurred_after_fix}


def root_cause_hypotheses(cv: ControlView, occurrences: list[dict], snap: Snapshot) -> list[dict]:
    hyps: list[dict] = []
    first = min(_aware(f.detected_at) for f in cv.findings)
    if len(cv.owner_history) > 1:
        changes = [o for o in cv.owner_history[1:] if o["from"] >= first.isoformat()[:10]]
        if changes:
            hyps.append({"factor": "Control owner changed",
                         "basis": f"Ownership changed {len(changes)} time(s) since first occurrence "
                                  f"(now {cv.owner_name}).", "signal": "owner_history"})
    if len(cv.tests) >= 3:
        gaps = [(_aware(a.tested_at) - _aware(b.tested_at)).days for a, b in zip(cv.tests, cv.tests[1:])]
        if max(gaps) - min(gaps) > cv.control.frequency_days * 0.5:
            hyps.append({"factor": "Testing process inconsistent",
                         "basis": f"Intervals between tests ranged {min(gaps)}–{max(gaps)} days against a "
                                  f"{cv.control.frequency_days}-day frequency.", "signal": "test_intervals"})
    if cv.control.automation == "manual":
        hyps.append({"factor": "Evidence collection is manual",
                     "basis": "Control is configured as manual; evidence depends on a person remembering the cycle.",
                     "signal": "control.automation"})
    for p in snap.policies:
        if cv.control.code in (p.parameters or {}).get("control_codes", []) and p.status != "ACTIVE":
            hyps.append({"factor": "Policy changed", "basis": f"Linked policy {p.code} status is {p.status}.",
                         "signal": "policy"})
    passed_then_recurred = any(v["result"] == "PASSED" for o in occurrences[:-1] for v in o["verification"])
    if passed_then_recurred and len(occurrences) > 1:
        hyps.append({"factor": "Remediation was temporary",
                     "basis": "A previous remediation passed verification, yet the same finding re-appeared — the fix "
                              "appears to have addressed the symptom (one review) rather than the recurring process.",
                     "signal": "verification_history"})
    return hyps


def detect_recurring(snap: Snapshot, include_closed: bool = False) -> list[dict]:
    out: list[dict] = []
    for cv in snap.in_scope_controls():
        by_cat: dict[str, list] = defaultdict(list)
        for f in cv.findings:
            by_cat[f.category].append(f)
        for cat, fs in by_cat.items():
            if len(fs) < 2:
                continue
            fs = sorted(fs, key=lambda f: _aware(f.detected_at))
            latest = fs[-1]
            active = latest.status in OPEN_FINDING_STATUSES
            if not active and not include_closed:
                continue
            occ = [_occurrence(f, snap) for f in fs]
            eff = effectiveness(occ)
            out.append({
                "control_code": cv.control.code, "control_name": cv.control.name, "control_id": cv.control.id,
                "category": cat, "title": latest.title,
                "first_detected": occ[0]["detected_at"], "occurrences": len(fs),
                "current_status": "RECURRING" if active else "HISTORICAL",
                "latest_finding": latest.code, "latest_severity": latest.severity,
                "previous_remediation": "Implemented" if any(o["remediation"] for o in occ[:-1]) else "None recorded",
                "verification_summary": f"Passed {eff['verifications_passed']}x, failed {eff['verifications_failed']}x",
                "effectiveness": eff,
                "timeline": occ,
                "hypotheses": root_cause_hypotheses(cv, occ, snap),
                "hypotheses_label": HYPOTHESIS_LABEL,
                "interpretation": (
                    "The previous remediation appears to have addressed the symptom but not the underlying process "
                    "weakness." if eff["recurred_after_remediation"] else
                    "The finding has recurred without a documented remediation between occurrences."),
                "interpretation_label": "AI-generated analysis — inspect evidence before acting",
            })
    return sorted(out, key=lambda r: -r["occurrences"])


def recent_window(snap: Snapshot, days: int = 365):
    return snap.now - timedelta(days=days)

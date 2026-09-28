"""Audit Readiness Report: structured data persisted to `reports`, rendered to a designed PDF on export."""
from __future__ import annotations

import io
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.compliance.readiness import posture
from app.compliance.snapshot import OPEN_FINDING_STATUSES, _aware, evidence_status, load_snapshot, next_upcoming_audit
from app.models import AuditLog, Company, Report
from app.risk.engine import merged_config
from app.schemas.serializers import finding_row


def build_readiness_report(db: Session, principal, audit_id: int | None = None, run_id: int | None = None) -> Report:
    cid = principal.company_id
    audit = None
    if audit_id is None:
        audit = next_upcoming_audit(db, cid)
        audit_id = audit.id if audit else None
    snap = load_snapshot(db, cid, audit_id=audit_id)
    audit = snap.audit or audit
    company = db.get(Company, cid)
    p = posture(snap, merged_config(company.settings))
    p.pop("_risks")
    gaps, recurring = p.pop("_gaps"), p.pop("_recurring")
    controls = snap.in_scope_controls()
    ids = {cv.control.id for cv in controls}
    open_f = [finding_row(f, snap) for f in snap.findings if f.status in OPEN_FINDING_STATUSES and f.control_id in ids]
    ev_counts: dict[str, int] = {}
    for cv in controls:
        for e in cv.evidence:
            s = evidence_status(e, snap.now)
            ev_counts[s] = ev_counts.get(s, 0) + 1
    active_plans = [pl for pl in snap.plans if pl.status not in ("COMPLETED", "CANCELLED")]
    tasks = [t for t in snap.tasks if any(pl.id == t.plan_id for pl in snap.plans)]
    trail = db.execute(select(AuditLog).where(AuditLog.company_id == cid).order_by(AuditLog.created_at.desc()).limit(15)).scalars().all()
    frameworks = sorted({f for cv in controls for f in cv.framework_codes})
    data = {
        "generated_at": snap.now.isoformat(), "company": company.name,
        "generated_by": principal.name, "disclaimer":
            "Prepared by NovaTech Compliance Intelligence (prototype). Indicators are not certification scores and this "
            "report is not legal advice. Further human review is recommended.",
        "audit": {"code": audit.code, "name": audit.name, "date": audit.start_date.isoformat(),
                  "framework": audit.framework.name} if audit else None,
        "framework": frameworks,
        "executive_summary": (
            f"NovaTech readiness indicator is {p['readiness']['overall']}% for "
            f"{audit.name if audit else 'the current scope'}. {p['gap_count']} potential gaps, "
            f"{p['critical_risks']} critical and {p['high_risks']} high-risk controls, {p['recurring_findings']} recurring "
            f"finding(s) and {p['evidence_expiring']} evidence item(s) expiring within 30 days were identified. "
            "Potential compliance gaps are listed with evidence references below."),
        "readiness": p["readiness"],
        "scope": {"controls": len(controls), "requirements": p["requirements_total"], "evidence": p["evidence_total"]},
        "control_status": p["control_status_counts"],
        "evidence_status": ev_counts,
        "open_findings": open_f,
        "recurring_findings": [{k: r[k] for k in ("control_code", "control_name", "title", "first_detected", "occurrences",
                                                  "previous_remediation", "verification_summary", "current_status")}
                               | {"effectiveness": r["effectiveness"]["level"]} for r in recurring],
        "risk_summary": {"counts": p["risk_counts"], "top": [{k: t[k] for k in ("code", "name", "status", "score", "category")}
                                                             for t in p["top_risks"]], "model": "NovaTech Prototype Risk Model"},
        "gaps": gaps["subjects"],
        "remediation": {"active_plans": len(active_plans), "tasks_total": len(tasks),
                        "tasks_completed": sum(t.status == "COMPLETED" for t in tasks),
                        "plans": [{"code": pl.code, "title": pl.title, "status": pl.status} for pl in active_plans][:10]},
        "recommended_actions": [
            {"priority": i + 1, "control": t["code"], "action": f"Address {t['name']} ({t['status'].replace('_', ' ').lower()})",
             "risk": t["category"]} for i, t in enumerate(p["top_risks"][:6])],
        "evidence_references": [{"code": e.code, "name": e.name, "control": cv.control.code,
                                 "status": evidence_status(e, snap.now), "collected": _aware(e.collected_at).date().isoformat()}
                                for cv in controls if cv.control.id in {r['id'] for r in p['top_risks']} for e in cv.evidence],
        "audit_trail": [{"at": _aware(a.created_at).isoformat(), "actor": a.actor_label, "action": a.action,
                         "result": a.result} for a in trail],
    }
    existing = db.execute(select(Report).where(Report.company_id == cid)).scalars().all()
    rep = Report(company_id=cid, code=f"RPT-{datetime.now(timezone.utc).year}-{len(existing) + 1:03d}",
                 report_type="audit_readiness", title=f"Audit Readiness Report — {audit.name if audit else 'Current scope'}",
                 audit_id=audit_id, generated_by=principal.user_id, agent_run_id=run_id, data=data)
    db.add(rep)
    db.flush()
    return rep


def render_pdf(rep: Report) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    d = rep.data
    navy, slate, line = colors.HexColor("#0f1b3d"), colors.HexColor("#475569"), colors.HexColor("#e2e8f0")
    tone = {"CRITICAL": "#b91c1c", "HIGH": "#c2410c", "MEDIUM": "#b45309", "LOW": "#047857"}
    ss = getSampleStyleSheet()
    H1 = ParagraphStyle("h1", parent=ss["Heading1"], textColor=navy, fontSize=18, spaceAfter=4)
    H2 = ParagraphStyle("h2", parent=ss["Heading2"], textColor=navy, fontSize=12, spaceBefore=12, spaceAfter=6)
    B = ParagraphStyle("b", parent=ss["BodyText"], fontSize=9, leading=13, textColor=colors.HexColor("#1e293b"))
    S = ParagraphStyle("s", parent=B, fontSize=7.5, textColor=slate)
    buf = io.BytesIO()

    def frame(c, doc):
        c.saveState()
        c.setFillColor(navy)
        c.rect(0, A4[1] - 14 * mm, A4[0], 14 * mm, fill=1, stroke=0)
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 10)
        c.drawString(15 * mm, A4[1] - 9 * mm, "NovaTech Compliance Intelligence")
        c.setFont("Helvetica", 8)
        c.drawRightString(A4[0] - 15 * mm, A4[1] - 9 * mm, f"{rep.code} · Prototype / Demonstration")
        c.setFillColor(slate)
        c.drawString(15 * mm, 10 * mm, "Not a certification. Not legal advice. Further human review is recommended.")
        c.drawRightString(A4[0] - 15 * mm, 10 * mm, f"Page {doc.page}")
        c.restoreState()

    def table(rows, widths, header=True):
        t = Table(rows, colWidths=widths, repeatRows=1 if header else 0)
        st = [("FONT", (0, 0), (-1, -1), "Helvetica", 8), ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#1e293b")),
              ("LINEBELOW", (0, 0), (-1, -1), 0.4, line), ("VALIGN", (0, 0), (-1, -1), "TOP"),
              ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]
        if header:
            st += [("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f5f9"))]
        t.setStyle(TableStyle(st))
        return t

    P = lambda s, st=B: Paragraph(str(s), st)  # noqa: E731
    story = [Spacer(1, 6 * mm), P(rep.title, H1),
             P(f"{d['company']} · generated {d['generated_at'][:16].replace('T', ' ')} UTC by {d['generated_by']}", S),
             Spacer(1, 4 * mm), P("Executive Summary", H2), P(d["executive_summary"])]
    ind = d["readiness"]["indicators"]
    cells = [[P(f"<font size=16 color='#0f1b3d'><b>{d['readiness']['overall']}%</b></font><br/>Overall", B)] +
             [P(f"<font size=13><b>{v['value']}%</b></font><br/>{v['label']}", B) for v in ind.values()]]
    mt = Table(cells, colWidths=[30 * mm] * 6)
    mt.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.5, line), ("INNERGRID", (0, 0), (-1, -1), 0.5, line),
                            ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
    story += [Spacer(1, 3 * mm), mt, P(d["readiness"]["label"] + " — " + d["readiness"]["disclaimer"], S)]
    if d.get("audit"):
        a = d["audit"]
        story += [P("Audit Scope", H2), P(f"{a['name']} ({a['framework']}) — scheduled {a['date']}. "
                                          f"{d['scope']['controls']} controls, {d['scope']['requirements']} requirements, "
                                          f"{d['scope']['evidence']} evidence items. Frameworks: {', '.join(d['framework'])} "
                                          "(Prototype / Demonstration Mapping).")]
    story += [P("Control Status", H2), table([["Status", "Controls"]] + [[k, v] for k, v in sorted(d["control_status"].items())], [60 * mm, 30 * mm]),
              P("Evidence Status", H2), table([["Status", "Items"]] + [[k, v] for k, v in sorted(d["evidence_status"].items())], [60 * mm, 30 * mm]),
              P("Risk Summary", H2),
              table([["Control", "Name", "Status", "Score", "Risk"]] +
                    [[t["code"], P(t["name"]), t["status"], t["score"], P(f"<font color='{tone[t['category']]}'><b>{t['category']}</b></font>")]
                     for t in d["risk_summary"]["top"]], [20 * mm, 70 * mm, 28 * mm, 18 * mm, 24 * mm]),
              P("Open Findings", H2),
              table([["Finding", "Title", "Control", "Severity", "Status"]] +
                    [[f["code"], P(f["title"]), f["control_code"], f["severity"], f["status"].replace("_", " ")] for f in d["open_findings"]],
                    [26 * mm, 72 * mm, 18 * mm, 20 * mm, 30 * mm])]
    if d["recurring_findings"]:
        story += [P("Recurring Findings", H2),
                  table([["Control", "Finding", "First seen", "Occ.", "Remediation effectiveness"]] +
                        [[r["control_code"], P(r["title"]), r["first_detected"], r["occurrences"], r["effectiveness"]]
                         for r in d["recurring_findings"]], [18 * mm, 74 * mm, 24 * mm, 12 * mm, 38 * mm]),
                  P("Recurrence interpretation is AI-generated analysis requiring human validation.", S)]
    story += [P("Remediation Progress", H2),
              P(f"{d['remediation']['active_plans']} active plans · {d['remediation']['tasks_completed']}/{d['remediation']['tasks_total']} tasks completed."),
              P("Recommended Actions", H2),
              table([["#", "Control", "Action", "Risk"]] + [[r["priority"], r["control"], P(r["action"]), r["risk"]] for r in d["recommended_actions"]],
                    [8 * mm, 20 * mm, 118 * mm, 20 * mm]),
              P("Evidence References", H2),
              table([["Evidence", "Name", "Control", "Status", "Collected"]] +
                    [[e["code"], P(e["name"]), e["control"], e["status"], e["collected"]] for e in d["evidence_references"][:20]],
                    [18 * mm, 80 * mm, 18 * mm, 24 * mm, 24 * mm]),
              P("Audit Trail (latest)", H2),
              table([["Time (UTC)", "Actor", "Action", "Result"]] +
                    [[a["at"][:19].replace("T", " "), a["actor"], P(a["action"]), a["result"] or ""] for a in d["audit_trail"]],
                    [32 * mm, 34 * mm, 76 * mm, 24 * mm]),
              Spacer(1, 4 * mm), P(d["disclaimer"], S)]
    SimpleDocTemplate(buf, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=20 * mm,
                      bottomMargin=18 * mm, title=rep.title).build(story, onFirstPage=frame, onLaterPages=frame)
    return buf.getvalue()

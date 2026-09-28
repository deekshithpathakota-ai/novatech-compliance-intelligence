"""Print the numbers the judge demo depends on (computed, never hardcoded)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.compliance.readiness import posture  # noqa: E402
from app.compliance.snapshot import load_snapshot, next_upcoming_audit  # noqa: E402
from app.database.session import SessionLocal  # noqa: E402

db = SessionLocal()
a = next_upcoming_audit(db, 1)
for label, snap in [(f"scope {a.code}", load_snapshot(db, 1, audit_id=a.id)), ("company", load_snapshot(db, 1))]:
    p = posture(snap)
    print(label, "readiness", p["readiness"]["overall"], {k: v["value"] for k, v in p["readiness"]["indicators"].items()})
    print("  open", p["open_findings"], "crit", p["critical_risks"], "high", p["high_risks"], "expiring", p["evidence_expiring"],
          "gaps", p["gap_count"], "recurring", p["recurring_findings"], "status", p["control_status_counts"])
    print("  subjects", [s["subject_code"] for s in p["_gaps"]["subjects"]])
    print("  top", [(t["code"], t["category"], t["score"]) for t in p["top_risks"]])

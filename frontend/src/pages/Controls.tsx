import { useNavigate, useSearchParams } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { DataTable, EmptyState, PageHeader, QueryView, RiskBadge, StatusBadge } from "@/components/app";
import { Select } from "@/components/ui/input";
import { api } from "@/lib/api";
import { cn, fmtDate } from "@/lib/utils";
import type { ControlRow } from "@/types";

const STATUSES = ["attention", "PASS", "AT_RISK", "PARTIAL", "FAIL", "OVERDUE", "EXPIRED", "NOT_TESTED"];

export function HealthBar({ c }: { c: ControlRow }) {
  const pct = c.days_since_test == null ? 100 : Math.min(100, Math.round((c.days_since_test / c.frequency_days) * 100));
  const tone = pct >= 100 ? "bg-danger" : pct >= 80 ? "bg-warning" : "bg-success";
  return (
    <div className="w-24" title={`${c.days_since_test ?? "never"} / ${c.frequency_days} days of test cycle elapsed`}>
      <div className="h-1.5 rounded-full bg-surface-2"><div className={cn("h-full rounded-full", tone)} style={{ width: `${pct}%` }} /></div>
      <div className="mt-0.5 text-[10.5px] text-muted tabular">{c.days_since_test ?? "—"}d / {c.frequency_days}d</div>
    </div>
  );
}

export default function Controls() {
  const [p, setP] = useSearchParams();
  const nav = useNavigate();
  const qs = new URLSearchParams();
  ["status", "framework", "risk"].forEach((k) => p.get(k) && qs.set(k, p.get(k)!));
  const q = useQuery({ queryKey: ["controls", qs.toString()], queryFn: () => api.get<ControlRow[]>(`/api/controls?${qs}`) });
  const set = (k: string, v: string) => { const n = new URLSearchParams(p); v ? n.set(k, v) : n.delete(k); setP(n); };
  return (
    <>
      <PageHeader eyebrow="Control Health" title="Controls" description="Every control with its framework mapping, owner, test cadence, evidence state, history and deterministic risk." />
      <div className="mb-4 flex flex-wrap gap-2">
        <Select aria-label="Status" value={p.get("status") ?? ""} onChange={(e) => set("status", e.target.value)}>
          <option value="">All statuses</option>{STATUSES.map((s) => <option key={s} value={s}>{s === "attention" ? "Needs attention" : s.replace("_", " ")}</option>)}
        </Select>
        <Select aria-label="Framework" value={p.get("framework") ?? ""} onChange={(e) => set("framework", e.target.value)}>
          <option value="">All frameworks</option>{["ISO27001", "SOC2", "NIST_CSF", "DPDP"].map((f) => <option key={f}>{f}</option>)}
        </Select>
        <Select aria-label="Risk" value={p.get("risk") ?? ""} onChange={(e) => set("risk", e.target.value)}>
          <option value="">All risk levels</option>{["CRITICAL", "HIGH", "MEDIUM", "LOW"].map((f) => <option key={f}>{f}</option>)}
        </Select>
        {q.data && <span className="self-center text-[12.5px] text-muted">{q.data.length} controls</span>}
      </div>
      <QueryView q={q}>
        {(rows) => (
          <DataTable rows={rows} rowKey={(r) => r.id} onRowClick={(r) => nav(`/controls/${r.id}`)}
            empty={<EmptyState title="No controls match these filters" />}
            columns={[
              { key: "code", header: "Control", cell: (r) => <span className="font-mono text-[12px] text-muted">{r.code}</span> },
              { key: "name", header: "Name", cell: (r) => <div className="min-w-[200px]"><div className="font-medium">{r.name}</div><div className="text-[11.5px] text-muted">{r.domain}</div></div> },
              { key: "fw", header: "Framework", hideOnMobile: true, cell: (r) => <span className="text-[12px] text-muted">{r.frameworks.join(", ") || "—"}</span> },
              { key: "owner", header: "Owner", hideOnMobile: true, cell: (r) => r.owner ?? <span className="text-danger">Unassigned</span> },
              { key: "health", header: "Test cycle", cell: (r) => <HealthBar c={r} /> },
              { key: "last", header: "Last tested", hideOnMobile: true, cell: (r) => <span className="whitespace-nowrap">{fmtDate(r.last_tested)}</span> },
              { key: "next", header: "Next test", hideOnMobile: true, cell: (r) => <span className={cn("whitespace-nowrap", r.next_test_overdue && "text-danger font-medium")}>{fmtDate(r.next_test)}</span> },
              { key: "ev", header: "Evidence", cell: (r) => <StatusBadge status={r.evidence_status} /> },
              { key: "hist", header: "Failures", hideOnMobile: true, cell: (r) => <span className="tabular">{r.historical_failures}</span> },
              { key: "risk", header: "Risk", cell: (r) => <RiskBadge risk={r.risk_category} score={r.risk_score} /> },
              { key: "status", header: "Status", cell: (r) => <StatusBadge status={r.status} /> },
            ]} />
        )}
      </QueryView>
    </>
  );
}

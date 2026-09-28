import { useNavigate, useSearchParams } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { Repeat } from "lucide-react";
import { DataTable, EmptyState, PageHeader, QueryView, RiskBadge, StatusBadge } from "@/components/app";
import { Select } from "@/components/ui/input";
import { api } from "@/lib/api";
import { fmtDate } from "@/lib/utils";
import type { FindingRow } from "@/types";

export default function Findings() {
  const [p, setP] = useSearchParams();
  const nav = useNavigate();
  const q = useQuery({ queryKey: ["findings"], queryFn: () => api.get<FindingRow[]>("/api/findings") });
  const set = (k: string, v: string) => { const n = new URLSearchParams(p); v ? n.set(k, v) : n.delete(k); setP(n); };
  const view = p.get("view") ?? "open";
  return (
    <>
      <PageHeader eyebrow="Findings" title="Findings" description="Current and historical findings across audits and continuous monitoring. Recurrence is detected from audit memory." />
      <QueryView q={q}>
        {(all) => {
          const depts = Array.from(new Set(all.map((f) => f.department).filter(Boolean))) as string[];
          const owners = Array.from(new Set(all.map((f) => f.owner).filter(Boolean))) as string[];
          let rows = all;
          if (view === "open") rows = rows.filter((f) => ["OPEN", "IN_REMEDIATION", "READY_FOR_CLOSURE"].includes(f.status));
          if (view === "closed") rows = rows.filter((f) => f.status === "CLOSED");
          const fl = { severity: p.get("severity"), framework: p.get("framework"), status: p.get("status"), department: p.get("department"), owner: p.get("owner"), recurring: p.get("recurring") };
          if (fl.severity) rows = rows.filter((f) => f.severity === fl.severity);
          if (fl.framework) rows = rows.filter((f) => f.frameworks.includes(fl.framework!));
          if (fl.status) rows = rows.filter((f) => f.status === fl.status);
          if (fl.department) rows = rows.filter((f) => f.department === fl.department);
          if (fl.owner) rows = rows.filter((f) => f.owner === fl.owner);
          if (fl.recurring) rows = rows.filter((f) => f.recurring === (fl.recurring === "yes"));
          return (
            <>
              <div className="mb-4 flex flex-wrap gap-2">
                <Select aria-label="View" value={view} onChange={(e) => set("view", e.target.value)}><option value="open">Open</option><option value="closed">Closed</option><option value="all">All</option></Select>
                <Select aria-label="Severity" value={fl.severity ?? ""} onChange={(e) => set("severity", e.target.value)}><option value="">Any severity</option>{["CRITICAL", "HIGH", "MEDIUM", "LOW"].map((s) => <option key={s}>{s}</option>)}</Select>
                <Select aria-label="Framework" value={fl.framework ?? ""} onChange={(e) => set("framework", e.target.value)}><option value="">Any framework</option>{["ISO27001", "SOC2", "NIST_CSF", "DPDP"].map((s) => <option key={s}>{s}</option>)}</Select>
                <Select aria-label="Status" value={fl.status ?? ""} onChange={(e) => set("status", e.target.value)}><option value="">Any status</option>{["OPEN", "IN_REMEDIATION", "READY_FOR_CLOSURE", "CLOSED"].map((s) => <option key={s} value={s}>{s.replace(/_/g, " ")}</option>)}</Select>
                <Select aria-label="Department" value={fl.department ?? ""} onChange={(e) => set("department", e.target.value)}><option value="">Any department</option>{depts.sort().map((s) => <option key={s}>{s}</option>)}</Select>
                <Select aria-label="Owner" value={fl.owner ?? ""} onChange={(e) => set("owner", e.target.value)}><option value="">Any owner</option>{owners.sort().map((s) => <option key={s}>{s}</option>)}</Select>
                <Select aria-label="Recurring" value={fl.recurring ?? ""} onChange={(e) => set("recurring", e.target.value)}><option value="">Recurring: any</option><option value="yes">Recurring</option><option value="no">Not recurring</option></Select>
                <span className="self-center text-[12.5px] text-muted">{rows.length} findings</span>
              </div>
              <DataTable rows={rows} rowKey={(r) => r.id} onRowClick={(r) => nav(`/findings/${r.id}`)}
                empty={<EmptyState title="You're all clear." description="No findings match these filters." />}
                columns={[
                  { key: "code", header: "Finding ID", cell: (r) => <span className="font-mono text-[12px] text-muted whitespace-nowrap">{r.code}</span> },
                  { key: "t", header: "Title", cell: (r) => <div className="min-w-[220px] font-medium">{r.title}</div> },
                  { key: "c", header: "Control", cell: (r) => <span className="font-mono text-[12px]">{r.control_code}</span> },
                  { key: "s", header: "Severity", cell: (r) => <RiskBadge risk={r.severity} /> },
                  { key: "st", header: "Status", cell: (r) => <StatusBadge status={r.status} /> },
                  { key: "o", header: "Owner", hideOnMobile: true, cell: (r) => r.owner ?? "—" },
                  { key: "d", header: "Due", hideOnMobile: true, cell: (r) => <span className="whitespace-nowrap">{fmtDate(r.due_date)}</span> },
                  { key: "r", header: "Recurring", cell: (r) => r.recurring ? <span className="inline-flex items-center gap-1 text-[12px] font-medium text-danger"><Repeat className="h-3.5 w-3.5" />{r.prior_occurrences + 1}×</span> : <span className="text-subtle">—</span> },
                  { key: "risk", header: "Risk", hideOnMobile: true, cell: (r) => <RiskBadge risk={r.risk} /> },
                  { key: "u", header: "Last updated", hideOnMobile: true, cell: (r) => <span className="whitespace-nowrap text-muted">{fmtDate(r.updated_at)}</span> },
                ]} />
            </>
          );
        }}
      </QueryView>
    </>
  );
}

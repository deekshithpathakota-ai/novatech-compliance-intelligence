import * as React from "react";
import { useQuery, keepPreviousData } from "@tanstack/react-query";
import { DataTable, PageHeader, QueryView, RiskBadge } from "@/components/app";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input, Select } from "@/components/ui/input";
import { api } from "@/lib/api";
import { fmtDateTime, title } from "@/lib/utils";

export default function AuditLogs() {
  const [page, setPage] = React.useState(1);
  const [actor, setActor] = React.useState("");
  const [auth, setAuth] = React.useState("");
  const [q, setQ] = React.useState("");
  const [term, setTerm] = React.useState("");
  const qs = new URLSearchParams({ page: String(page), page_size: "50" });
  if (actor) qs.set("actor_type", actor);
  if (auth) qs.set("authorization", auth);
  if (term) qs.set("q", term);
  const data = useQuery({ queryKey: ["audit-logs", qs.toString()], queryFn: () => api.get<any>(`/api/audit-logs?${qs}`), placeholderData: keepPreviousData });
  return (
    <>
      <PageHeader eyebrow="Complete audit trail" title="Audit logs" description="Every user action, agent tool call, authorization decision and approval — stored in the database with tenant, role, risk and result." />
      <form onSubmit={(e) => { e.preventDefault(); setTerm(q); setPage(1); }} className="mb-4 flex flex-wrap gap-2">
        <Input className="max-w-xs" placeholder="Search action, resource, actor…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search logs" />
        <Select aria-label="Actor" value={actor} onChange={(e) => { setActor(e.target.value); setPage(1); }}><option value="">All actors</option><option value="user">User</option><option value="agent">Compliance Agent</option><option value="system">System</option></Select>
        <Select aria-label="Authorization" value={auth} onChange={(e) => { setAuth(e.target.value); setPage(1); }}><option value="">Any authorization</option><option value="ALLOWED">Allowed</option><option value="DENIED">Denied</option></Select>
        <Button type="submit">Search</Button>
      </form>
      <QueryView q={data}>
        {(d) => (
          <>
            <DataTable dense rows={d.items} rowKey={(r: any) => r.id} columns={[
              { key: "at", header: "Timestamp", cell: (r: any) => <span className="whitespace-nowrap font-mono text-[11.5px] text-muted">{fmtDateTime(r.at)}</span> },
              { key: "a", header: "Actor", cell: (r: any) => <div className="whitespace-nowrap"><div className="font-medium">{r.actor}</div><div className="text-[11px] text-muted">{r.role ? title(r.role) : title(r.actor_type)}</div></div> },
              { key: "ac", header: "Action", cell: (r: any) => <div className="min-w-[220px]">{r.action}{r.reason && <div className="text-[11px] text-muted">{r.reason}</div>}</div> },
              { key: "res", header: "Resource", hideOnMobile: true, cell: (r: any) => <span className="font-mono text-[11.5px]">{r.resource ?? "—"}</span> },
              { key: "tool", header: "Tool / run", hideOnMobile: true, cell: (r: any) => r.tool ? <span className="font-mono text-[11px] text-muted">{r.tool}{r.agent_run_id ? ` #${r.agent_run_id}` : ""}</span> : "—" },
              { key: "risk", header: "Risk", hideOnMobile: true, cell: (r: any) => <RiskBadge risk={r.risk_level} /> },
              { key: "auth", header: "Authorization", cell: (r: any) => <Badge tone={r.authorization === "DENIED" ? "danger" : "success"}>{r.authorization}</Badge> },
              { key: "r", header: "Result", cell: (r: any) => <span className="text-[12px]">{r.result ? title(r.result) : "—"}</span> },
            ]} />
            <div className="mt-3 flex items-center justify-between text-[12.5px] text-muted">
              <span>{d.total.toLocaleString()} events · page {d.page} of {Math.max(1, Math.ceil(d.total / d.page_size))}</span>
              <div className="flex gap-2"><Button size="sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</Button><Button size="sm" disabled={page * d.page_size >= d.total} onClick={() => setPage(page + 1)}>Next</Button></div>
            </div>
          </>
        )}
      </QueryView>
    </>
  );
}

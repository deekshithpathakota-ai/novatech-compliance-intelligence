import { Link, useNavigate, useParams } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { FileBarChart, Play, Sparkles } from "lucide-react";
import { toast } from "sonner";
import { DataTable, EmptyState, KV, PageHeader, QueryView, RiskBadge, StatusBadge, Timeline } from "@/components/app";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Progress } from "@/components/ui/misc";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useAuth } from "@/hooks/useAuth";
import { api, ApiError } from "@/lib/api";
import { fmtDate, title } from "@/lib/utils";
import { HealthBar } from "./Controls";

export default function AuditDetail() {
  const { id } = useParams();
  const nav = useNavigate();
  const { can } = useAuth();
  const q = useQuery({ queryKey: ["audit", id], queryFn: () => api.get<any>(`/api/audits/${id}`) });
  const report = async () => {
    try { const r = await api.post<any>(`/api/reports/audit-readiness?audit_id=${id}`); nav(`/reports/${r.id}`); }
    catch (e) { toast.error((e as ApiError).message); }
  };
  return (
    <QueryView q={q}>
      {(a) => (
        <>
          <PageHeader eyebrow={<Link to="/audits" className="hover:underline">Audits</Link>} title={a.name}
            description={`${a.framework} · ${title(a.type)} · ${fmtDate(a.start_date)} · ${a.auditor}${a.outcome ? ` · ${a.outcome}` : ""}`}
            actions={<>
              {a.status !== "completed" && can("AGENT_USE") && <Button onClick={() => nav(`/agent?q=${encodeURIComponent("Prepare NovaTech for our upcoming ISO 27001-style audit.")}`)}><Sparkles className="h-3.5 w-3.5 text-accent" />Prepare Audit</Button>}
              {a.status === "completed" && <Button onClick={() => nav(`/audits/${a.id}/replay`)}><Play className="h-3.5 w-3.5" />Replay Audit</Button>}
              {can("REPORTS_GENERATE") && <Button variant="primary" onClick={report}><FileBarChart className="h-3.5 w-3.5" />Generate report</Button>}
            </>} />
          <Tabs defaultValue="overview">
            <TabsList>{["overview", "requirements", "controls", "findings", "remediation", "timeline", "agent analysis"].map((t) => <TabsTrigger key={t} value={t}>{title(t)}</TabsTrigger>)}</TabsList>
            <TabsContent value="overview">
              <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
                <Card className="p-5"><div className="text-[12px] text-muted">{a.status === "completed" ? "Readiness today (same scope)" : "NovaTech readiness indicator"}</div><div className="mt-1 text-[32px] font-semibold tabular">{a.readiness.overall}%</div><Progress value={a.readiness.overall} className="mt-2" /><p className="mt-2 text-[11px] text-subtle">{a.readiness.disclaimer}</p></Card>
                <Card className="p-5 lg:col-span-2"><KV items={[
                  ["Status", <StatusBadge status={a.status === "completed" ? "COMPLETED" : a.status.toUpperCase()} />], ["Scope", `${a.requirements.length} requirements · ${a.controls.length} controls`],
                  ["Findings", a.findings.length], ["Potential gaps (today)", a.gaps.length], ["Recurring findings", a.recurring.length], ["Summary", a.summary || "—"],
                ]} /></Card>
              </div>
            </TabsContent>
            <TabsContent value="requirements">
              <DataTable rows={a.requirements} rowKey={(r: any) => r.id} columns={[
                { key: "c", header: "Requirement", cell: (r: any) => <span className="font-mono text-[12px] text-muted">{r.code}</span> },
                { key: "t", header: "Title", cell: (r: any) => r.title },
                { key: "m", header: "Mapped", cell: (r: any) => r.mapped ? <Badge tone="success">Mapped</Badge> : <Badge tone="danger">No control</Badge> },
                { key: "s", header: "Status", cell: (r: any) => <StatusBadge status={r.status === "changed" ? "CHANGED" : "ACTIVE"} /> },
              ]} />
            </TabsContent>
            <TabsContent value="controls">
              <DataTable rows={a.controls} rowKey={(r: any) => r.id} onRowClick={(r: any) => nav(`/controls/${r.id}`)} columns={[
                { key: "c", header: "Control", cell: (r: any) => <span className="font-mono text-[12px] text-muted">{r.code}</span> },
                { key: "n", header: "Name", cell: (r: any) => r.name },
                { key: "h", header: "Test cycle", cell: (r: any) => <HealthBar c={r} /> },
                { key: "e", header: "Evidence", cell: (r: any) => <StatusBadge status={r.evidence_status} /> },
                { key: "r", header: "Risk", cell: (r: any) => <RiskBadge risk={r.risk_category} score={r.risk_score} /> },
                { key: "s", header: "Status", cell: (r: any) => <StatusBadge status={r.status} /> },
              ]} />
            </TabsContent>
            <TabsContent value="findings">
              <DataTable rows={a.findings} rowKey={(r: any) => r.id} onRowClick={(r: any) => nav(`/findings/${r.id}`)} empty={<EmptyState title="No findings" />} columns={[
                { key: "c", header: "Finding", cell: (r: any) => <span className="font-mono text-[12px] text-muted">{r.code}</span> },
                { key: "t", header: "Title", cell: (r: any) => r.title },
                { key: "ctl", header: "Control", cell: (r: any) => r.control_code },
                { key: "s", header: "Severity", cell: (r: any) => <RiskBadge risk={r.severity} /> },
                { key: "st", header: "Status", cell: (r: any) => <StatusBadge status={r.status} /> },
              ]} />
            </TabsContent>
            <TabsContent value="remediation">
              <DataTable rows={a.remediation} rowKey={(r: any) => r.id} empty={<EmptyState title="No remediation linked" />} columns={[
                { key: "c", header: "Plan", cell: (r: any) => <span className="font-mono text-[12px] text-muted">{r.code}</span> },
                { key: "t", header: "Title", cell: (r: any) => r.title },
                { key: "s", header: "Status", cell: (r: any) => <StatusBadge status={r.status} /> },
              ]} />
            </TabsContent>
            <TabsContent value="timeline"><Card className="p-5"><Timeline items={a.timeline.slice(0, 40)} /></Card></TabsContent>
            <TabsContent value="agent analysis">
              <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
                <Card><CardHeader title="Potential gaps" /><CardBody className="space-y-1.5">
                  {a.gaps.map((g: any) => <div key={g.subject_code} className="flex items-center justify-between gap-2 text-[13px]"><span><span className="font-mono text-muted">{g.subject_code}</span> {g.subject_name}</span><RiskBadge risk={g.severity} /></div>)}
                </CardBody></Card>
                <Card><CardHeader title="Recurring findings" /><CardBody className="space-y-2 text-[13px]">
                  {a.recurring.length ? a.recurring.map((r: any) => <div key={r.control_code}><b>{r.control_code}</b> {r.control_name} — {r.occurrences} occurrences, effectiveness {r.effectiveness.level}</div>) : <p className="text-muted">None.</p>}
                </CardBody></Card>
              </div>
            </TabsContent>
          </Tabs>
        </>
      )}
    </QueryView>
  );
}

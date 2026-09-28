import { Link, useParams } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { Download, FileSpreadsheet } from "lucide-react";
import { toast } from "sonner";
import { PageHeader, QueryView, RiskBadge, StatusBadge } from "@/components/app";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Progress } from "@/components/ui/misc";
import { api, download } from "@/lib/api";
import { fmtDate, fmtDateTime, title } from "@/lib/utils";

function T({ head, rows }: { head: string[]; rows: React.ReactNode[][] }) {
  return (
    <div className="overflow-x-auto scrollbar-thin">
      <table className="w-full text-[12.5px]">
        <thead className="text-[11px] uppercase tracking-wider text-muted"><tr>{head.map((h) => <th key={h} className="py-1.5 pr-3 text-left">{h}</th>)}</tr></thead>
        <tbody className="divide-y divide-border">{rows.map((r, i) => <tr key={i}>{r.map((c, j) => <td key={j} className="py-1.5 pr-3">{c}</td>)}</tr>)}</tbody>
      </table>
    </div>
  );
}

export default function ReportView() {
  const { id } = useParams();
  const q = useQuery({ queryKey: ["report", id], queryFn: () => api.get<any>(`/api/reports/${id}`) });
  return (
    <QueryView q={q}>
      {(r) => {
        const d = r.data;
        return (
          <>
            <PageHeader eyebrow={<Link to="/reports" className="hover:underline">Reports · {r.code}</Link>} title={r.title}
              description={`${d.company} · generated ${fmtDateTime(d.generated_at)} by ${d.generated_by}`}
              actions={<>
                <Button onClick={() => download(`/api/reports/${r.id}/csv`, `${r.code}.csv`).catch(() => toast.error("Export failed"))}><FileSpreadsheet className="h-4 w-4" />CSV</Button>
                <Button variant="primary" onClick={() => download(`/api/reports/${r.id}/pdf`, `${r.code}.pdf`).catch(() => toast.error("Export failed"))}><Download className="h-4 w-4" />Export PDF</Button>
              </>} />
            <div className="space-y-5">
              <Card><CardHeader title="Executive summary" /><CardBody>
                <p className="text-[13.5px] leading-relaxed">{d.executive_summary}</p>
                <div className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-6">
                  <div className="rounded-lg bg-primary px-3 py-2.5 text-primary-foreground"><div className="text-[11px] opacity-80">Overall</div><div className="text-[24px] font-semibold tabular">{d.readiness.overall}%</div></div>
                  {Object.values(d.readiness.indicators).map((v: any) => (
                    <div key={v.label} className="rounded-lg bg-surface-2 px-3 py-2.5"><div className="text-[11px] text-muted">{v.label}</div><div className="text-[18px] font-semibold tabular">{v.value}%</div><Progress value={v.value} className="mt-1" /></div>
                  ))}
                </div>
                <p className="mt-2 text-[11px] text-subtle">{d.readiness.label} — {d.readiness.disclaimer}</p>
              </CardBody></Card>
              <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
                <Card><CardHeader title="Audit scope" /><CardBody className="text-[13px] space-y-1">
                  {d.audit && <><div className="font-medium">{d.audit.name}</div><div className="text-muted">{d.audit.framework} · {fmtDate(d.audit.date)}</div></>}
                  <div>{d.scope.controls} controls · {d.scope.requirements} requirements · {d.scope.evidence} evidence items</div>
                  <div className="flex flex-wrap gap-1 pt-1">{d.framework.map((f: string) => <Badge key={f} tone="neutral">{f}</Badge>)}</div>
                </CardBody></Card>
                <Card><CardHeader title="Control status" /><CardBody className="space-y-1">{Object.entries(d.control_status).map(([k, v]: any) => <div key={k} className="flex justify-between text-[13px]"><StatusBadge status={k} /><b className="tabular">{v}</b></div>)}</CardBody></Card>
                <Card><CardHeader title="Evidence status" /><CardBody className="space-y-1">{Object.entries(d.evidence_status).map(([k, v]: any) => <div key={k} className="flex justify-between text-[13px]"><StatusBadge status={k} /><b className="tabular">{v}</b></div>)}</CardBody></Card>
              </div>
              <Card><CardHeader title="Risk summary" description={d.risk_summary.model} /><CardBody>
                <T head={["Control", "Name", "Status", "Risk"]} rows={d.risk_summary.top.map((t: any) => [<span className="font-mono">{t.code}</span>, t.name, <StatusBadge status={t.status} />, <RiskBadge risk={t.category} score={t.score} />])} />
              </CardBody></Card>
              <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
                <Card><CardHeader title={`Open findings · ${d.open_findings.length}`} /><CardBody>
                  <T head={["Finding", "Title", "Severity", "Status"]} rows={d.open_findings.map((f: any) => [<Link to={`/findings/${f.id}`} className="font-mono text-accent hover:underline">{f.code}</Link>, f.title, <RiskBadge risk={f.severity} />, <StatusBadge status={f.status} />])} />
                </CardBody></Card>
                <Card><CardHeader title={`Recurring findings · ${d.recurring_findings.length}`} description="AI-generated interpretation requires human validation" /><CardBody>
                  <T head={["Control", "First seen", "Occurrences", "Effectiveness"]} rows={d.recurring_findings.map((x: any) => [x.control_code, fmtDate(x.first_detected), x.occurrences, <Badge tone={x.effectiveness === "LOW" ? "danger" : "warning"}>{x.effectiveness}</Badge>])} />
                </CardBody></Card>
              </div>
              <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
                <Card><CardHeader title="Recommended actions" /><CardBody>
                  <ol className="space-y-1.5 text-[13px]">{d.recommended_actions.map((a: any) => <li key={a.priority} className="flex gap-2"><span className="w-4 text-muted tabular">{a.priority}</span><span className="flex-1">{a.action}</span><RiskBadge risk={a.risk} /></li>)}</ol>
                  <div className="mt-3 text-[12.5px] text-muted">Remediation: {d.remediation.active_plans} active plans · {d.remediation.tasks_completed}/{d.remediation.tasks_total} tasks completed</div>
                </CardBody></Card>
                <Card><CardHeader title="Evidence references" /><CardBody>
                  <T head={["Evidence", "Name", "Control", "Status"]} rows={d.evidence_references.slice(0, 12).map((e: any) => [<span className="font-mono">{e.code}</span>, e.name, e.control, <StatusBadge status={e.status} />])} />
                </CardBody></Card>
              </div>
              <Card><CardHeader title="Audit trail" /><CardBody>
                <T head={["Time", "Actor", "Action", "Result"]} rows={d.audit_trail.map((a: any) => [fmtDateTime(a.at), a.actor, a.action, a.result ? title(a.result) : "—"])} />
              </CardBody></Card>
              <p className="text-[11.5px] text-subtle">{d.disclaimer}</p>
            </div>
          </>
        );
      }}
    </QueryView>
  );
}

import { Link, useNavigate } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { Area, AreaChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Sparkles } from "lucide-react";
import { PageHeader, QueryView, RiskBadge } from "@/components/app";
import { BriefView } from "@/components/app/lab";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Progress } from "@/components/ui/misc";
import { api } from "@/lib/api";
import { fmtDate } from "@/lib/utils";

export default function Executive() {
  const q = useQuery({ queryKey: ["dashboard"], queryFn: () => api.get<any>("/api/dashboard") });
  const audits = useQuery({ queryKey: ["audits"], queryFn: () => api.get<any[]>("/api/audits") });
  const brief = useQuery({ queryKey: ["brief"], queryFn: () => api.get<any>("/api/brief") });
  const plans = useQuery({ queryKey: ["remediation"], queryFn: () => api.get<any[]>("/api/remediation") });
  const nav = useNavigate();
  return (
    <QueryView q={q}>
      {(d) => {
        const active = (plans.data ?? []).filter((p) => !["COMPLETED", "CANCELLED"].includes(p.status));
        const prog = active.length ? Math.round(active.reduce((a, p) => a + p.progress, 0) / active.length) : 100;
        return (
          <>
            <PageHeader eyebrow="Executive View" title="Compliance posture" description="Readiness, critical risks and progress — without the operational detail."
              actions={<Button variant="primary" onClick={() => nav("/agent")}><Sparkles className="h-4 w-4" />Ask Compliance Agent</Button>} />
            {brief.data && <div className="mb-5"><BriefView b={brief.data} compact /></div>}
            <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
              <Card className="p-6">
                <div className="text-[12.5px] text-muted">Overall readiness · {d.upcoming_audit?.name}</div>
                <div className="mt-1 text-[44px] font-semibold tracking-tight tabular">{d.metrics.readiness}%</div>
                <Progress value={d.metrics.readiness} />
                <p className="mt-2 text-[11.5px] text-subtle">{d.readiness.label} — not a certification score.</p>
              </Card>
              <Card className="lg:col-span-2"><CardHeader title="Readiness trend" /><CardBody className="h-[170px]">
                <ResponsiveContainer><AreaChart data={d.charts.readiness_trend} margin={{ left: -20, right: 8 }}>
                  <XAxis dataKey="date" tick={{ fontSize: 11, fill: "var(--muted)" }} axisLine={false} tickLine={false} tickFormatter={(s) => fmtDate(s, { day: "2-digit", month: "short" })} />
                  <YAxis domain={[60, 100]} tick={{ fontSize: 11, fill: "var(--muted)" }} axisLine={false} tickLine={false} />
                  <Tooltip contentStyle={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 12 }} formatter={(v: any) => [`${v}%`, "Readiness"]} />
                  <Area dataKey="readiness" stroke="var(--accent)" fill="var(--accent)" fillOpacity={0.12} strokeWidth={2} />
                </AreaChart></ResponsiveContainer>
              </CardBody></Card>
              <Card><CardHeader title={`Critical risks · ${d.metrics.critical_risks}`} /><CardBody className="space-y-2">
                {d.top_risks.filter((t: any) => ["CRITICAL", "HIGH"].includes(t.category)).map((t: any) => (
                  <Link key={t.code} to={`/controls/${t.id}`} className="flex items-center justify-between gap-2 text-[13px] hover:underline"><span>{t.name}</span><RiskBadge risk={t.category} /></Link>
                ))}
              </CardBody></Card>
              <Card><CardHeader title={`Top unresolved findings · ${d.metrics.open_findings}`} /><CardBody className="space-y-2 text-[13px]">
                <div className="flex justify-between"><span className="text-muted">Recurring</span><b>{d.metrics.recurring_findings}</b></div>
                <div className="flex justify-between"><span className="text-muted">Overdue remediation tasks</span><b>{d.metrics.overdue_remediation}</b></div>
                <div className="flex justify-between"><span className="text-muted">Evidence expiring (30d)</span><b>{d.metrics.evidence_expiring}</b></div>
                <Link to="/findings" className="block pt-1 text-accent hover:underline">View findings →</Link>
              </CardBody></Card>
              <Card><CardHeader title="Remediation progress" /><CardBody>
                <div className="text-[28px] font-semibold tabular">{prog}%</div><Progress value={prog} tone="success" />
                <div className="mt-2 text-[12.5px] text-muted">{active.length} active plans</div>
              </CardBody></Card>
              <Card className="lg:col-span-3"><CardHeader title="Upcoming audits" /><CardBody className="grid grid-cols-1 gap-3 md:grid-cols-2">
                {(audits.data ?? []).filter((a) => a.status !== "completed").map((a) => (
                  <Link key={a.id} to={`/audits/${a.id}`} className="rounded-lg border border-border p-4 hover:bg-surface-2">
                    <div className="flex items-center justify-between"><b className="text-[14px]">{a.name}</b><span className="text-[12.5px] text-muted">{fmtDate(a.start_date)} · in {a.days_until}d</span></div>
                    <div className="mt-2 flex items-center gap-3"><span className="text-[22px] font-semibold tabular">{a.readiness}%</span><Progress value={a.readiness} /></div>
                    <div className="mt-1 text-[12px] text-muted">{a.critical_gaps} critical · {a.open_findings} open findings · evidence coverage {a.evidence_coverage}%</div>
                  </Link>
                ))}
              </CardBody></Card>
            </div>
          </>
        );
      }}
    </QueryView>
  );
}

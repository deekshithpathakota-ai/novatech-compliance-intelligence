import { Link, useNavigate } from "react-router";
import { useQuery } from "@tanstack/react-query";
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Legend, PolarAngleAxis, PolarGrid, PolarRadiusAxis, Radar, RadarChart,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { AlertTriangle, CalendarClock, FileWarning, Gauge, Repeat, ShieldAlert, Sparkles } from "lucide-react";
import { BriefView } from "@/components/app/lab";
import { MetricCard, PageHeader, QueryView, RiskBadge, StatusBadge, Timeline } from "@/components/app";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { api } from "@/lib/api";
import { fmtDate, title } from "@/lib/utils";

const tip = { contentStyle: { background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 12, color: "var(--foreground)" }, cursor: { fill: "var(--surface-2)" } };
const axis = { tick: { fontSize: 11, fill: "var(--muted)" }, axisLine: false, tickLine: false } as const;
const STATUS_COLOR: Record<string, string> = { PASS: "var(--success)", AT_RISK: "var(--warning)", PARTIAL: "var(--warning)", OVERDUE: "var(--danger)", FAIL: "var(--danger)", EXPIRED: "var(--danger)", NOT_TESTED: "var(--subtle)" };

export default function CommandCenter() {
  const q = useQuery({ queryKey: ["dashboard"], queryFn: () => api.get<any>("/api/dashboard") });
  const brief = useQuery({ queryKey: ["brief"], queryFn: () => api.get<any>("/api/brief") });
  const nav = useNavigate();
  const hour = new Date().getHours();
  return (
    <QueryView q={q}>
      {(d) => {
        const m = d.metrics;
        const ua = d.upcoming_audit;
        return (
          <>
            <PageHeader
              eyebrow="Command Center"
              title={`Good ${hour < 12 ? "morning" : hour < 17 ? "afternoon" : "evening"}, ${d.user.split(" ")[0]}`}
              description="Here's what needs your attention."
              actions={<>
                <Link to="/readiness"><Button variant="secondary"><Gauge className="h-4 w-4" />Audit readiness</Button></Link>
                <Link to={`/agent?q=${encodeURIComponent("Prepare NovaTech for our upcoming ISO 27001-style audit.")}`}><Button variant="primary"><Sparkles className="h-4 w-4" />Prepare for audit</Button></Link>
              </>}
            />
            {brief.data && <div className="mb-5"><BriefView b={brief.data} /></div>}
            <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
              <MetricCard label="Compliance Readiness" value={`${m.readiness}%`} tone="info" hint={ua ? `${ua.name.replace(" 2026", "")} scope` : "All controls"} to="/readiness" />
              <MetricCard label="Critical Risks" value={m.critical_risks} tone="danger" hint={`${m.high_risks} high-risk controls`} icon={<ShieldAlert className="h-4 w-4" />} to="/controls?risk=CRITICAL" />
              <MetricCard label="Open Findings" value={m.open_findings} tone="danger" hint={`${m.recurring_findings} recurring`} icon={<AlertTriangle className="h-4 w-4" />} to="/findings" />
              <MetricCard label="Evidence Expiring" value={m.evidence_expiring} tone="warning" hint="within 30 days" icon={<FileWarning className="h-4 w-4" />} to="/evidence?status=EXPIRING" />
              <MetricCard label="Overdue Controls" value={m.overdue_controls} tone="warning" hint={`${m.overdue_remediation} overdue remediation tasks`} to="/controls?status=OVERDUE" />
              <MetricCard label="Upcoming Audit" value={ua ? `${ua.days}d` : "—"} tone="neutral" hint={ua ? fmtDate(ua.date) : "None scheduled"} icon={<CalendarClock className="h-4 w-4" />} to={ua ? `/audits/${ua.id}` : "/audits"} />
            </div>
            <p className="mt-2 text-[11.5px] text-subtle">{d.readiness.label} — {d.readiness.disclaimer}</p>

            <div className="mt-5 grid grid-cols-1 gap-5 xl:grid-cols-[minmax(0,1fr)_380px]">
              <div className="grid grid-cols-1 min-w-0 content-start items-start gap-5 md:grid-cols-2">
                <Card>
                  <CardHeader title="Compliance Risk Radar" description="Risk by area (100 − indicator). Click an area to open it." />
                  <CardBody className="h-[260px]">
                    <ResponsiveContainer>
                      <RadarChart data={d.radar} outerRadius="62%" margin={{ left: 24, right: 24, top: 8, bottom: 8 }}>
                        <PolarGrid stroke="var(--border)" />
                        <PolarAngleAxis dataKey="axis" tick={(p: any) => {
                          const item = d.radar.find((r: any) => r.axis === p.payload.value);
                          return <text x={p.x} y={p.y} textAnchor={p.textAnchor} fontSize={11} fill="var(--muted)" style={{ cursor: "pointer" }} onClick={() => nav(item.link)}>{p.payload.value}<tspan fill={item.level === "LOW" ? "var(--success)" : item.level === "MEDIUM" ? "var(--warning)" : "var(--danger)"}> · {item.level[0] + item.level.slice(1).toLowerCase()}</tspan></text>;
                        }} />
                        <PolarRadiusAxis domain={[0, 50]} tick={false} axisLine={false} />
                        <Radar dataKey="risk" stroke="var(--danger)" fill="var(--danger)" fillOpacity={0.18} strokeWidth={1.5} />
                        <Tooltip {...tip} formatter={(v: any) => [`${v}`, "Risk"]} />
                      </RadarChart>
                    </ResponsiveContainer>
                  </CardBody>
                </Card>
                <Card>
                  <CardHeader title="Control Health" description={`${m.controls_total} controls · derived status`} action={<Link to="/controls" className="text-[12px] text-accent hover:underline">View all</Link>} />
                  <CardBody className="h-[260px]">
                    <ResponsiveContainer>
                      <BarChart data={d.charts.control_health} margin={{ left: -18, right: 8 }}>
                        <CartesianGrid vertical={false} stroke="var(--border)" />
                        <XAxis dataKey="status" {...axis} interval={0} tick={{ fontSize: 10, fill: "var(--muted)" }} tickFormatter={(s) => title(s)} />
                        <YAxis {...axis} allowDecimals={false} />
                        <Tooltip {...tip} labelFormatter={(s) => title(String(s))} />
                        <Bar dataKey="count" radius={[4, 4, 0, 0]} maxBarSize={36} onClick={(e: any) => nav(`/controls?status=${e.status}`)} style={{ cursor: "pointer" }}>
                          {d.charts.control_health.map((c: any) => <Cell key={c.status} fill={STATUS_COLOR[c.status] ?? "var(--accent)"} />)}
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                  </CardBody>
                </Card>
                <Card>
                  <CardHeader title="Finding Trend" description="Opened vs closed · last 12 months" />
                  <CardBody className="h-[230px]">
                    <ResponsiveContainer>
                      <AreaChart data={d.charts.finding_trend} margin={{ left: -18, right: 8 }}>
                        <CartesianGrid vertical={false} stroke="var(--border)" />
                        <XAxis dataKey="month" {...axis} tickFormatter={(s) => new Date(s + "-01").toLocaleDateString("en-GB", { month: "short" })} />
                        <YAxis {...axis} allowDecimals={false} />
                        <Tooltip {...tip} />
                        <Legend wrapperStyle={{ fontSize: 11 }} />
                        <Area type="monotone" dataKey="opened" stroke="var(--danger)" fill="var(--danger)" fillOpacity={0.08} strokeWidth={1.8} />
                        <Area type="monotone" dataKey="closed" stroke="var(--success)" fill="var(--success)" fillOpacity={0.08} strokeWidth={1.8} />
                      </AreaChart>
                    </ResponsiveContainer>
                  </CardBody>
                </Card>
                <Card>
                  <CardHeader title="Audit Readiness Trend" description={ua ? `${ua.name}` : "Readiness snapshots"} />
                  <CardBody className="h-[230px]">
                    <ResponsiveContainer>
                      <AreaChart data={d.charts.readiness_trend} margin={{ left: -18, right: 8 }}>
                        <CartesianGrid vertical={false} stroke="var(--border)" />
                        <XAxis dataKey="date" {...axis} tickFormatter={(s) => fmtDate(s, { day: "2-digit", month: "short" })} />
                        <YAxis {...axis} domain={[60, 100]} />
                        <Tooltip {...tip} formatter={(v: any) => [`${v}%`, "Readiness"]} labelFormatter={(s) => fmtDate(String(s))} />
                        <Area type="monotone" dataKey="readiness" stroke="var(--accent)" fill="var(--accent)" fillOpacity={0.12} strokeWidth={2} />
                      </AreaChart>
                    </ResponsiveContainer>
                  </CardBody>
                </Card>
                <Card>
                  <CardHeader title="Remediation Progress" description="Active plans" action={<Link to="/remediation" className="text-[12px] text-accent hover:underline">Open</Link>} />
                  <CardBody className="h-[200px]">
                    <ResponsiveContainer>
                      <BarChart data={d.charts.remediation_progress} layout="vertical" margin={{ left: 30, right: 16 }}>
                        <XAxis type="number" {...axis} allowDecimals={false} />
                        <YAxis type="category" dataKey="state" {...axis} width={100} />
                        <Tooltip {...tip} />
                        <Bar dataKey="count" radius={[0, 4, 4, 0]} maxBarSize={18}>
                          {d.charts.remediation_progress.map((r: any) => <Cell key={r.state} fill={r.state === "Completed" ? "var(--success)" : r.state === "Overdue" ? "var(--danger)" : r.state === "Awaiting approval" ? "var(--warning)" : "var(--accent)"} />)}
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                  </CardBody>
                </Card>
                <Card>
                  <CardHeader title="Evidence Freshness" description="Current evidence items" action={<Link to="/evidence" className="text-[12px] text-accent hover:underline">Open</Link>} />
                  <CardBody className="h-[200px]">
                    <ResponsiveContainer>
                      <BarChart data={d.charts.evidence_freshness} margin={{ left: -18, right: 8 }}>
                        <CartesianGrid vertical={false} stroke="var(--border)" />
                        <XAxis dataKey="label" {...axis} tickFormatter={(s) => title(s)} />
                        <YAxis {...axis} allowDecimals={false} />
                        <Tooltip {...tip} labelFormatter={(s) => title(String(s))} />
                        <Bar dataKey="count" radius={[4, 4, 0, 0]} maxBarSize={40}>
                          {d.charts.evidence_freshness.map((r: any) => <Cell key={r.label} fill={{ FRESH: "var(--success)", AGING: "var(--chart-6)", EXPIRING: "var(--warning)", EXPIRED: "var(--danger)" }[r.label as string]} />)}
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                  </CardBody>
                </Card>
                <Card className="md:col-span-2">
                  <CardHeader title="Risk by Framework" description="Controls per risk category · Prototype / Demonstration Mapping" />
                  <CardBody className="h-[220px]">
                    <ResponsiveContainer>
                      <BarChart data={d.charts.risk_by_framework} margin={{ left: -18, right: 8 }}>
                        <CartesianGrid vertical={false} stroke="var(--border)" />
                        <XAxis dataKey="framework" {...axis} />
                        <YAxis {...axis} allowDecimals={false} />
                        <Tooltip {...tip} />
                        <Legend wrapperStyle={{ fontSize: 11 }} />
                        <Bar dataKey="LOW" stackId="a" fill="var(--success)" maxBarSize={48} />
                        <Bar dataKey="MEDIUM" stackId="a" fill="var(--warning)" />
                        <Bar dataKey="HIGH" stackId="a" fill="var(--danger)" />
                        <Bar dataKey="CRITICAL" stackId="a" fill="var(--critical)" radius={[4, 4, 0, 0]} />
                      </BarChart>
                    </ResponsiveContainer>
                  </CardBody>
                </Card>
              </div>

              <div className="space-y-5 self-start">
                <Card>
                  <CardHeader title="AI Recommendations" icon={<Sparkles className="h-4 w-4 text-accent" />} description="Next best actions from current compliance state" />
                  <CardBody className="space-y-3">
                    {d.recommendations.map((r: any, i: number) => (
                      <div key={i} className="rounded-lg border border-border p-3">
                        <div className="flex items-start justify-between gap-2">
                          <div className="text-[13px] font-semibold">{r.title}</div>
                          <RiskBadge risk={r.severity} />
                        </div>
                        <p className="mt-1 text-[12.5px] text-muted">{r.detail}</p>
                        <div className="mt-2 flex flex-wrap gap-2">
                          {r.actions.map((a: any) => (
                            <Button key={a.label} size="sm" variant={a.kind === "agent" ? "primary" : "secondary"}
                              onClick={() => a.kind === "agent" ? nav(`/agent?q=${encodeURIComponent(a.prompt)}`) : nav(a.to)}>
                              {a.kind === "agent" && <Sparkles className="h-3 w-3" />}{a.label}
                            </Button>
                          ))}
                        </div>
                      </div>
                    ))}
                  </CardBody>
                </Card>
                <Card>
                  <CardHeader title="Top risks" icon={<Repeat className="h-4 w-4 text-danger" />} description="NovaTech Prototype Risk Model" />
                  <CardBody className="space-y-1.5">
                    {d.top_risks.slice(0, 6).map((t: any) => (
                      <Link key={t.code} to={`/controls/${t.id}`} className="flex items-center gap-2 rounded-md px-1.5 py-1.5 text-[13px] hover:bg-surface-2">
                        <span className="font-mono text-[11.5px] text-muted">{t.code}</span><span className="min-w-0 flex-1 truncate">{t.name}</span><StatusBadge status={t.status} /><RiskBadge risk={t.category} score={t.score} />
                      </Link>
                    ))}
                  </CardBody>
                </Card>
                <Card>
                  <CardHeader title="Audit Timeline" description="Latest compliance events — persistent memory" action={<Badge tone="accent">Live</Badge>} />
                  <CardBody><Timeline items={d.timeline} /></CardBody>
                </Card>
              </div>
            </div>
          </>
        );
      }}
    </QueryView>
  );
}

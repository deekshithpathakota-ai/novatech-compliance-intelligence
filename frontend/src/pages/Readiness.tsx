import { Link, useNavigate } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { CalendarClock, Sparkles } from "lucide-react";
import { EmptyState, PageHeader, QueryView, RiskBadge, StatusBadge } from "@/components/app";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Progress } from "@/components/ui/misc";
import { api } from "@/lib/api";
import { fmtDate, title } from "@/lib/utils";

function Gauge({ value }: { value: number }) {
  const r = 52, c = 2 * Math.PI * r, off = c * (1 - value / 100);
  const color = value >= 85 ? "var(--success)" : value >= 70 ? "var(--accent)" : "var(--warning)";
  return (
    <svg viewBox="0 0 128 128" className="h-36 w-36" role="img" aria-label={`Overall readiness ${value}%`}>
      <circle cx="64" cy="64" r={r} fill="none" stroke="var(--surface-2)" strokeWidth="12" />
      <circle cx="64" cy="64" r={r} fill="none" stroke={color} strokeWidth="12" strokeLinecap="round" strokeDasharray={c} strokeDashoffset={off} transform="rotate(-90 64 64)" style={{ transition: "stroke-dashoffset .6s" }} />
      <text x="64" y="62" textAnchor="middle" fontSize="28" fontWeight="600" fill="var(--foreground)" fontFamily="Inter">{value}%</text>
      <text x="64" y="80" textAnchor="middle" fontSize="10" fill="var(--muted)" fontFamily="Inter">overall</text>
    </svg>
  );
}

export default function Readiness() {
  const audits = useQuery({ queryKey: ["audits"], queryFn: () => api.get<any[]>("/api/audits") });
  const upcoming = audits.data?.filter((a) => a.status !== "completed").sort((a, b) => a.start_date.localeCompare(b.start_date)) ?? [];
  const first = upcoming[0];
  const detail = useQuery({ queryKey: ["readiness", first?.id], queryFn: () => api.post<any>(`/api/audits/${first.id}/readiness`), enabled: !!first });
  const nav = useNavigate();
  return (
    <>
      <PageHeader eyebrow="Audit Readiness" title="Audit readiness" description="Framework scope, control health, evidence, findings, remediation and recurring issues — computed from live state."
        actions={first && <Button variant="primary" onClick={() => nav(`/agent?q=${encodeURIComponent("Prepare NovaTech for our upcoming ISO 27001-style audit.")}`)}><Sparkles className="h-4 w-4" />Prepare for upcoming audit</Button>} />
      <QueryView q={audits}>
        {() => !first ? <EmptyState title="No upcoming audits" /> : (
          <QueryView q={detail}>
            {(d) => (
              <div className="space-y-5">
                <Card className="p-5">
                  <div className="flex flex-col gap-6 md:flex-row md:items-center">
                    <Gauge value={d.readiness.overall} />
                    <div className="flex-1 space-y-3">
                      <div className="flex flex-wrap items-center gap-2"><CalendarClock className="h-4 w-4 text-accent" /><span className="text-[15px] font-semibold">{first.name}</span><Badge tone="neutral">{fmtDate(first.start_date)} · in {first.days_until} days</Badge></div>
                      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-5">
                        {Object.entries(d.readiness.indicators).map(([k, v]: any) => (
                          <div key={k}>
                            <div className="flex justify-between text-[12.5px]"><span className="text-muted">{v.label}</span><b className="tabular">{v.value}%</b></div>
                            <Progress value={v.value} tone={v.value >= 85 ? "success" : v.value >= 70 ? "accent" : "warning"} className="mt-1" />
                            <div className="mt-1 text-[11px] text-subtle">{v.basis}</div>
                          </div>
                        ))}
                      </div>
                      <p className="text-[11.5px] text-subtle">{d.readiness.label} — {d.readiness.disclaimer}</p>
                    </div>
                  </div>
                </Card>
                <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
                  <Card><CardHeader title={`Potential gaps · ${d.gaps.gap_count}`} description="16 deterministic checks over the audit scope" /><CardBody className="space-y-1.5">
                    {d.gaps.subjects.map((s: any) => (
                      <div key={s.subject_code} className="flex flex-wrap items-center gap-2 border-b border-border py-2 text-[13px] last:border-0">
                        <span className="w-[72px] font-mono text-[12px] text-muted">{s.subject_code}</span><span className="min-w-0 flex-1 font-medium">{s.subject_name}</span>
                        <span className="text-[11.5px] text-muted">{s.gap_types.map(title).join(" · ")}</span><RiskBadge risk={s.severity} />
                      </div>
                    ))}
                  </CardBody></Card>
                  <Card><CardHeader title="Top risks before audit" description="Simulated pre-audit review — which controls are weakest" /><CardBody className="space-y-1.5">
                    {d.top_risks.map((t: any, i: number) => (
                      <Link key={t.code} to={`/controls/${t.id}`} className="flex items-center gap-3 rounded-md px-1 py-1.5 text-[13px] hover:bg-surface-2">
                        <span className="w-4 text-right text-muted tabular">{i + 1}</span><span className="min-w-0 flex-1 truncate"><span className="font-mono text-[12px] text-muted">{t.code}</span> {t.name}</span><StatusBadge status={t.status} /><RiskBadge risk={t.category} score={t.score} />
                      </Link>
                    ))}
                    <div className="pt-2"><Button size="sm" variant="primary" onClick={() => nav(`/agent?q=${encodeURIComponent("Create a remediation plan for the top three risks")}`)}>Start Remediation</Button></div>
                  </CardBody></Card>
                  <Card><CardHeader title={`Evidence expiring · ${d.expiring_items.length}`} /><CardBody className="space-y-1.5">
                    {d.expiring_items.map((e: any) => (
                      <div key={e.code} className="flex items-center justify-between gap-2 text-[13px]"><span><span className="font-mono text-[12px] text-muted">{e.code}</span> {e.name}</span><Badge tone={e.days_left <= 14 ? "danger" : "warning"}>{e.days_left}d</Badge></div>
                    ))}
                  </CardBody></Card>
                  <Card><CardHeader title={`Recurring findings · ${d.recurring.length}`} /><CardBody className="space-y-2">
                    {d.recurring.map((r: any) => (
                      <Link key={r.control_code} to={`/controls/${r.control_id}`} className="block rounded-lg border border-border p-3 text-[13px] hover:bg-surface-2">
                        <div className="flex items-center justify-between"><b>{r.control_code} {r.control_name}</b><Badge tone="danger">{r.occurrences}×</Badge></div>
                        <div className="mt-1 text-[12px] text-muted">First detected {fmtDate(r.first_detected)} · effectiveness {r.effectiveness.level}</div>
                      </Link>
                    ))}
                  </CardBody></Card>
                </div>
                {upcoming.length > 1 && (
                  <Card><CardHeader title="Upcoming audits" /><CardBody className="grid grid-cols-1 gap-3 md:grid-cols-2">
                    {upcoming.map((a) => (
                      <Link key={a.id} to={`/audits/${a.id}`} className="rounded-lg border border-border p-4 hover:bg-surface-2">
                        <div className="flex items-center justify-between"><b className="text-[13.5px]">{a.name}</b><Badge tone="neutral">{fmtDate(a.start_date)}</Badge></div>
                        <div className="mt-2 grid grid-cols-4 gap-2 text-[12px]">
                          <div><div className="text-muted">Readiness</div><b>{a.readiness}%</b></div><div><div className="text-muted">Critical gaps</div><b>{a.critical_gaps}</b></div>
                          <div><div className="text-muted">Open findings</div><b>{a.open_findings}</b></div><div><div className="text-muted">Evidence</div><b>{a.evidence_coverage}%</b></div>
                        </div>
                      </Link>
                    ))}
                  </CardBody></Card>
                )}
              </div>
            )}
          </QueryView>
        )}
      </QueryView>
    </>
  );
}

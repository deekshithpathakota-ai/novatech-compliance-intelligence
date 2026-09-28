import { Link } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { CalendarClock, CheckCircle2 } from "lucide-react";
import { PageHeader, QueryView, StatusBadge } from "@/components/app";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Progress } from "@/components/ui/misc";
import { api } from "@/lib/api";
import { fmtDate, title } from "@/lib/utils";

export default function Audits() {
  const q = useQuery({ queryKey: ["audits"], queryFn: () => api.get<any[]>("/api/audits") });
  return (
    <>
      <PageHeader eyebrow="Audit memory" title="Audits" description="Upcoming audits with live readiness, and the completed audits whose findings, remediation and verification the agent remembers." />
      <QueryView q={q}>
        {(rows) => {
          const up = rows.filter((a) => a.status !== "completed");
          const past = rows.filter((a) => a.status === "completed");
          return (
            <div className="space-y-6">
              <section>
                <h2 className="mb-2 flex items-center gap-2 text-[13px] font-semibold uppercase tracking-wider text-muted"><CalendarClock className="h-4 w-4" />Upcoming audits</h2>
                <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                  {up.map((a) => (
                    <Link key={a.id} to={`/audits/${a.id}`}><Card className="h-full p-5 transition-shadow hover:shadow-pop">
                      <div className="flex items-start justify-between gap-2"><div><div className="text-[15px] font-semibold">{a.name}</div><div className="text-[12.5px] text-muted">{a.framework} · {a.auditor}</div></div><Badge tone="accent">in {a.days_until}d</Badge></div>
                      <div className="mt-4 flex items-end gap-3"><div className="text-[30px] font-semibold tabular">{a.readiness}%</div><div className="mb-1.5 text-[12px] text-muted">NovaTech readiness indicator</div></div>
                      <Progress value={a.readiness} className="mt-1" />
                      <div className="mt-4 grid grid-cols-4 gap-2 text-[12px]">
                        <div><div className="text-muted">Date</div><b>{fmtDate(a.start_date, { day: "2-digit", month: "short" })}</b></div>
                        <div><div className="text-muted">Critical gaps</div><b className="text-danger">{a.critical_gaps}</b></div>
                        <div><div className="text-muted">Open findings</div><b>{a.open_findings}</b></div>
                        <div><div className="text-muted">Evidence coverage</div><b>{a.evidence_coverage}%</b></div>
                      </div>
                    </Card></Link>
                  ))}
                </div>
              </section>
              <section>
                <h2 className="mb-2 flex items-center gap-2 text-[13px] font-semibold uppercase tracking-wider text-muted"><CheckCircle2 className="h-4 w-4" />Completed audits</h2>
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
                  {past.map((a) => (
                    <Link key={a.id} to={`/audits/${a.id}`}><Card className="h-full p-4 transition-shadow hover:shadow-pop">
                      <div className="flex items-center justify-between gap-2"><span className="font-mono text-[11.5px] text-muted">{a.code}</span><StatusBadge status="COMPLETED" /></div>
                      <div className="mt-1 text-[14px] font-semibold">{a.name}</div>
                      <div className="text-[12px] text-muted">{fmtDate(a.start_date)} · {title(a.type)} · {a.auditor}</div>
                      <div className="mt-3 flex items-center justify-between text-[12.5px]"><span className="text-muted">{a.outcome}</span><Badge tone={a.findings ? "warning" : "success"}>{a.findings} findings</Badge></div>
                    </Card></Link>
                  ))}
                </div>
              </section>
            </div>
          );
        }}
      </QueryView>
    </>
  );
}

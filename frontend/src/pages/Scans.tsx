import * as React from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Radar } from "lucide-react";
import { toast } from "sonner";
import { DataTable, EmptyState, KV, PageHeader, QueryView, StatusBadge } from "@/components/app";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { useAuth } from "@/hooks/useAuth";
import { api, ApiError } from "@/lib/api";
import { cn, fmtDateTime, relDays, title } from "@/lib/utils";

export default function Scans() {
  const q = useQuery({ queryKey: ["scans"], queryFn: () => api.get<any>("/api/scans") });
  const qc = useQueryClient();
  const { can } = useAuth();
  const [busy, setBusy] = React.useState(false);
  const [last, setLast] = React.useState<any>(null);
  const refresh = () => ["scans", "nav-counts", "notifications", "findings", "dashboard"].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
  const run = async () => {
    setBusy(true);
    try { const r = await api.post<any>("/api/scans/run"); setLast(r); toast.success(`Scan complete — ${r.alerts} alerts, ${r.new_findings.length} new findings`); refresh(); }
    catch (e) { toast.error((e as ApiError).message); } finally { setBusy(false); }
  };
  const schedule = async (frequency: string, enabled: boolean) => {
    try { await api.put("/api/scans/schedule", { frequency, enabled }); toast.success(`Schedule: ${frequency}${enabled ? "" : " (paused)"}`); refresh(); }
    catch (e) { toast.error((e as ApiError).message); }
  };
  return (
    <>
      <PageHeader eyebrow="Operations" title="Scheduled compliance scans"
        description="The agent checks evidence freshness, overdue controls, unresolved findings and remediation deadlines on a schedule, raises findings for new gaps and sends alerts."
        actions={can("AUDIT_RUN") && <Button variant="primary" loading={busy} onClick={run}><Radar className="h-4 w-4" />Run scan now</Button>} />
      <QueryView q={q}>
        {(d) => (
          <div className="space-y-5">
            <div className="grid grid-cols-1 gap-5 lg:grid-cols-[360px_minmax(0,1fr)]">
              <Card><CardHeader title="Schedule" description={d.label} /><CardBody className="space-y-4">
                <div className="flex gap-2">
                  {["daily", "weekly", "monthly"].map((f) => (
                    <button key={f} disabled={!can("AUDIT_RUN") && !can("SETTINGS_MANAGE")} onClick={() => schedule(f, d.schedule.enabled)}
                      className={cn("flex-1 rounded-lg border px-3 py-2 text-[13px] font-medium cursor-pointer disabled:cursor-default", d.schedule.frequency === f ? "border-accent bg-accent-soft text-accent" : "border-border text-muted")}>{title(f)}</button>
                  ))}
                </div>
                <KV items={[["Status", d.schedule.enabled ? <Badge tone="success">Enabled</Badge> : <Badge tone="neutral">Paused</Badge>],
                  ["Last run", d.schedule.last_run_at ? `${fmtDateTime(d.schedule.last_run_at)} (${relDays(d.schedule.last_run_at)})` : "—"],
                  ["Next run", d.schedule.next_run_at ? `${fmtDateTime(d.schedule.next_run_at)} (${relDays(d.schedule.next_run_at)})` : "—"],
                  ["Checks", "Evidence freshness · overdue tests · unresolved findings · remediation deadlines · new control gaps"],
                  ["Alerts", "Demo Notifications to compliance officers and control owners (deduplicated for 24h)"]]} />
                {(can("AUDIT_RUN") || can("SETTINGS_MANAGE")) && <Button size="sm" onClick={() => schedule(d.schedule.frequency, !d.schedule.enabled)}>{d.schedule.enabled ? "Pause schedule" : "Enable schedule"}</Button>}
              </CardBody></Card>
              <Card><CardHeader title={last ? "Latest result" : "Most recent scan"} /><CardBody>
                {(() => {
                  const s = last ?? d.history[0]?.summary;
                  if (!s) return <EmptyState title="No scans yet" />;
                  return (
                    <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
                      {[["Evidence expiring ≤14d", s.evidence_expiring, "warning"], ["Evidence expired", s.evidence_expired, "danger"], ["Overdue tests", s.overdue_controls, "danger"],
                        ["Open findings", s.open_findings], ["Findings past due", s.findings_past_due, "warning"], ["Remediation deadlines", s.remediation_deadlines, "warning"],
                        ["New findings", s.new_findings.length, "danger"], ["Readiness", `${s.readiness}%`]].map(([k, v, t]: any) => (
                        <div key={k} className="rounded-lg bg-surface-2 px-3 py-2.5"><div className="text-[11.5px] text-muted">{k}</div><div className={cn("text-[20px] font-semibold tabular", t === "danger" && v ? "text-danger" : t === "warning" && v ? "text-warning" : "")}>{v}</div></div>
                      ))}
                    </div>
                  );
                })()}
              </CardBody></Card>
            </div>
            <DataTable rows={d.history} rowKey={(r: any) => r.id} empty={<EmptyState title="No scan history" />} columns={[
              { key: "at", header: "Run", cell: (r: any) => <span className="whitespace-nowrap">{fmtDateTime(r.at)}</span> },
              { key: "t", header: "Trigger", cell: (r: any) => <Badge tone={r.trigger === "scheduled" ? "accent" : "neutral"}>{r.trigger}</Badge> },
              { key: "a", header: "Alerts", cell: (r: any) => r.summary?.alerts ?? "—" },
              { key: "n", header: "New findings", cell: (r: any) => r.summary?.new_findings?.join(", ") || "0" },
              { key: "sent", header: "Notifications", hideOnMobile: true, cell: (r: any) => r.summary?.notifications_sent ?? "—" },
              { key: "r", header: "Readiness", cell: (r: any) => r.summary ? `${r.summary.readiness}%` : "—" },
              { key: "d", header: "Duration", hideOnMobile: true, cell: (r: any) => r.duration_ms ? `${r.duration_ms} ms` : "—" },
              { key: "s", header: "Status", cell: (r: any) => <StatusBadge status={r.status} /> },
            ]} />
          </div>
        )}
      </QueryView>
    </>
  );
}

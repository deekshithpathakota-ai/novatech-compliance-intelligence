import * as React from "react";
import { Link } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, ScanSearch } from "lucide-react";
import { ErrorState, KV, LoadingState, PageHeader, QueryView, RiskBadge, StatusBadge } from "@/components/app";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { api } from "@/lib/api";
import { fmtDate } from "@/lib/utils";

function ImpactDialog({ id, onClose }: { id: number; onClose: () => void }) {
  const qc = useQueryClient();
  const m = useMutation({ mutationFn: () => api.post<any>("/api/regulatory-changes/analyze", { change_id: id }), onSuccess: () => qc.invalidateQueries({ queryKey: ["regulatory"] }) });
  React.useEffect(() => { m.mutate(); }, [id]); // eslint-disable-line react-hooks/exhaustive-deps
  const d = m.data;
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent side="right" title={d ? `${d.change.code} · ${d.change.title}` : "Change impact"} description="Old version → new version → diff → affected requirements, controls, departments, evidence, findings → new risk">
        {m.isPending ? <LoadingState label="Analysing change impact…" rows={3} /> : m.error ? <ErrorState error={m.error} /> : d && (
          <div className="space-y-4 text-[13px]">
            <p className="font-medium">{d.summary}</p>
            {d.diff.length > 0 && (
              <div><div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-subtle">Diff · v{d.change.old_version} → v{d.change.new_version}</div>
                <p className="rounded-lg border border-border bg-surface-2 p-3 leading-relaxed">
                  {d.diff.map((t: any, i: number) => <span key={i} className={t.op === "add" ? "bg-success-soft text-success" : t.op === "del" ? "bg-danger-soft text-danger line-through" : ""}>{t.text} </span>)}
                </p>
                <p className="mt-1 text-[12px] text-muted">{d.change_summary}</p></div>
            )}
            {d.no_mapped_control && <p className="rounded-lg bg-danger-soft px-3 py-2 text-danger">Requirement currently has no mapped control.</p>}
            <KV items={[["Requirement", d.requirement ? `${d.requirement.code} — ${d.requirement.title}` : "—"], ["Effective", fmtDate(d.change.effective_date)],
              ["Departments", d.affected_departments.join(", ") || "—"], ["Upcoming audits", d.upcoming_audits.map((a: any) => a.name).join(", ") || "—"],
              ["Misaligned controls", d.misaligned_controls.join(", ") || "None"], ["New risk", <RiskBadge risk={d.new_risk} />], ["Source", d.change.source]]} />
            <div><div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-subtle">Affected controls</div>
              {d.affected_controls.map((c: any) => <div key={c.code} className="flex items-center justify-between border-b border-border py-1.5"><span><span className="font-mono text-muted">{c.code}</span> {c.name}</span><span className="flex gap-1"><StatusBadge status={c.status} /><RiskBadge risk={c.category} score={c.score} /></span></div>)}</div>
            <div><div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-subtle">Affected evidence · {d.affected_evidence.length}</div>
              {d.affected_evidence.map((e: any) => <div key={e.code} className="flex justify-between py-1"><span><span className="font-mono text-muted">{e.code}</span> {e.name}</span><StatusBadge status={e.status} /></div>)}</div>
            <div><div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-subtle">Affected findings · {d.affected_findings.length}</div>
              {d.affected_findings.map((f: any) => <Link key={f.id} to={`/findings/${f.id}`} className="block py-1 hover:underline"><span className="font-mono text-muted">{f.code}</span> {f.title}</Link>)}</div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

export default function Regulatory() {
  const q = useQuery({ queryKey: ["regulatory"], queryFn: () => api.get<any[]>("/api/regulatory-changes") });
  const [open, setOpen] = React.useState<number | null>(null);
  return (
    <>
      <PageHeader eyebrow="Regulatory Change Center" title="Regulatory changes" description="New and updated requirements with affected controls. Records are synthetic demo changes, clearly labelled with their source." />
      <QueryView q={q}>
        {(rows) => (
          <>
            <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4">
              {[["New", rows.filter((r) => r.change_type === "NEW").length], ["Updated", rows.filter((r) => r.change_type === "UPDATED").length],
                ["Effective soon", rows.filter((r) => r.status === "EFFECTIVE_SOON").length], ["Impact assessment required", rows.filter((r) => r.status === "IMPACT_ASSESSMENT_REQUIRED").length]].map(([k, v]) => (
                <Card key={k as string} className="px-4 py-3"><div className="text-[12px] text-muted">{k}</div><div className="text-[24px] font-semibold tabular">{v}</div></Card>
              ))}
            </div>
            <div className="space-y-3">
              {rows.map((r) => (
                <Card key={r.id} className="p-4">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge tone={r.change_type === "NEW" ? "accent" : "info"}>{r.change_type}</Badge><span className="font-mono text-[12px] text-muted">{r.requirement?.code}</span>
                    <span className="text-[14px] font-semibold">{r.title}</span><span className="ml-auto flex gap-2"><RiskBadge risk={r.risk} /><StatusBadge status={r.status} /></span>
                  </div>
                  <div className="mt-2 flex flex-wrap items-center gap-2 text-[12.5px] text-muted">
                    <span>v{r.old_version ?? "—"}</span><ArrowRight className="h-3.5 w-3.5" /><span className="font-medium text-foreground">v{r.new_version}</span>
                    <span>· effective {fmtDate(r.effective_date)}</span><span>· {r.source}</span>
                  </div>
                  <div className="mt-2 flex flex-wrap items-center justify-between gap-2 text-[13px]"><span><b>Action required:</b> {r.action_required}</span>
                    <Button size="sm" variant="primary" onClick={() => setOpen(r.id)}><ScanSearch className="h-3.5 w-3.5" />Review Impact</Button></div>
                  <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[12px]"><span className="text-muted">Affected controls:</span>
                    {r.affected_controls.length ? r.affected_controls.map((c: any) => <Link key={c.id} to={`/controls/${c.id}`}><Badge tone={c.status === "PASS" ? "success" : "warning"}>{c.code} {c.name}</Badge></Link>) : <Badge tone="danger">No mapped control</Badge>}
                  </div>
                </Card>
              ))}
            </div>
          </>
        )}
      </QueryView>
      {open && <ImpactDialog id={open} onClose={() => setOpen(null)} />}
    </>
  );
}

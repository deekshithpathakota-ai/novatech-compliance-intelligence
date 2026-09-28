import * as React from "react";
import { Link } from "react-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Inbox, Upload } from "lucide-react";
import { toast } from "sonner";
import { EmptyState, PageHeader, QueryView, RiskBadge, StatusBadge } from "@/components/app";
import { BriefView } from "@/components/app/lab";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Input, Label } from "@/components/ui/input";
import { useAuth } from "@/hooks/useAuth";
import { api, ApiError } from "@/lib/api";
import { fmtDate } from "@/lib/utils";

function UploadFor({ control, onClose, preset }: { control: any; onClose: () => void; preset?: string }) {
  const qc = useQueryClient();
  const [busy, setBusy] = React.useState(false);
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent title={`Upload evidence · ${control.code}`} description={control.name}>
        <form className="space-y-3" onSubmit={async (e) => {
          e.preventDefault();
          const fd = new FormData(e.currentTarget);
          fd.set("control_id", String(control.id));
          if (!(fd.get("file") as File)?.size) { toast.error("Choose a file."); return; }
          setBusy(true);
          try {
            const r = await api.upload<any>("/api/evidence", fd);
            toast.success(`${r.evidence.code} uploaded${r.fulfilled_requests?.length ? ` — fulfils ${r.fulfilled_requests.join(", ")}` : ""}`);
            ["workspace", "evidence", "controls", "nav-counts"].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
            onClose();
          } catch (err) { toast.error((err as ApiError).message); } finally { setBusy(false); }
        }}>
          <div className="space-y-1"><Label htmlFor="n">Evidence name</Label><Input id="n" name="name" required defaultValue={preset ?? ""} /></div>
          <div className="space-y-1"><Label htmlFor="v">Valid for (days)</Label><Input id="v" name="valid_days" type="number" defaultValue={90} min={1} max={730} /></div>
          <div className="space-y-1"><Label htmlFor="f">File</Label><Input id="f" name="file" type="file" className="pt-1.5" accept=".pdf,.docx,.txt,.md,.csv,.xlsx" /></div>
          <div className="flex justify-end gap-2"><Button type="button" onClick={onClose}>Cancel</Button><Button variant="primary" type="submit" loading={busy}>Upload</Button></div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export default function MyWork() {
  const { user } = useAuth();
  const q = useQuery({ queryKey: ["workspace"], queryFn: () => api.get<any>("/api/workspace/me") });
  const brief = useQuery({ queryKey: ["brief"], queryFn: () => api.get<any>("/api/brief") });
  const qc = useQueryClient();
  const [up, setUp] = React.useState<{ control: any; preset?: string } | null>(null);
  const complete = async (t: any) => {
    try { await api.post(`/api/remediation/tasks/${t.id}`, { status: "COMPLETED" }); toast.success("Task completed"); qc.invalidateQueries({ queryKey: ["workspace"] }); }
    catch (e) { toast.error((e as ApiError).message); }
  };
  return (
    <>
      <PageHeader eyebrow="Control Owner Workspace" title="My work" description={`Controls, evidence requests, findings, tasks and tests assigned to ${user?.name}.`} />
      {brief.data && <div className="mb-5"><BriefView b={brief.data} compact /></div>}
      <QueryView q={q}>
        {(d) => (
          <div className="grid grid-cols-1 gap-5 xl:grid-cols-2">
            <Card><CardHeader title={`Evidence requests · ${d.evidence_requests.length}`} description="Delivered as Demo Notifications" /><CardBody className="space-y-2">
              {d.evidence_requests.length ? d.evidence_requests.map((r: any) => (
                <div key={r.id} className="rounded-lg border border-border p-3">
                  <div className="flex flex-wrap items-center gap-2"><span className="font-mono text-[12px] text-muted">{r.code}</span><b className="text-[13px]">{r.control.code} {r.control.name}</b>{r.overdue ? <Badge tone="danger">Overdue</Badge> : <Badge tone="warning">Due {fmtDate(r.due_date)}</Badge>}</div>
                  <div className="mt-1 text-[13px]">{r.evidence_required}</div>
                  <div className="text-[12px] text-muted">{r.reason} · requested by {r.requested_by}</div>
                  <Button size="sm" variant="primary" className="mt-2" onClick={() => setUp({ control: r.control, preset: r.evidence_required })}><Upload className="h-3.5 w-3.5" />Upload evidence</Button>
                </div>
              )) : <EmptyState title="No open requests" icon={<Inbox className="h-5 w-5" />} />}
            </CardBody></Card>
            <Card><CardHeader title={`Remediation tasks · ${d.tasks.length}`} /><CardBody className="space-y-1.5">
              {d.tasks.length ? d.tasks.map((t: any) => (
                <div key={t.id} className="flex flex-wrap items-center gap-2 border-b border-border py-2 text-[13px] last:border-0">
                  <span className="min-w-0 flex-1">{t.title}<span className="block text-[11.5px] text-muted">due {fmtDate(t.due_date)} · evidence: {t.evidence_required}</span></span>
                  <RiskBadge risk={t.risk} /><StatusBadge status={t.overdue ? "OVERDUE" : t.status} />
                  {!t.action_type && t.risk === "LOW" && ["PENDING", "IN_PROGRESS"].includes(t.status) && <Button size="sm" onClick={() => complete(t)}>Complete</Button>}
                </div>
              )) : <p className="text-[13px] text-muted">No tasks assigned to you.</p>}
            </CardBody></Card>
            <Card><CardHeader title={`My controls · ${d.controls.length}`} /><CardBody className="space-y-1.5">
              {d.controls.map((c: any) => (
                <div key={c.id} className="flex flex-wrap items-center gap-2 border-b border-border py-2 text-[13px] last:border-0">
                  <Link to={`/controls/${c.id}`} className="min-w-0 flex-1 hover:underline"><span className="font-mono text-[12px] text-muted">{c.code}</span> {c.name}</Link>
                  <StatusBadge status={c.evidence_status} /><StatusBadge status={c.status} />
                  <Button size="sm" variant="ghost" onClick={() => setUp({ control: c })}><Upload className="h-3.5 w-3.5" />Evidence</Button>
                </div>
              ))}
            </CardBody></Card>
            <div className="space-y-5">
              <Card><CardHeader title={`Open findings · ${d.open_findings.length}`} /><CardBody className="space-y-1.5">
                {d.open_findings.length ? d.open_findings.map((f: any) => (
                  <Link key={f.id} to={`/findings/${f.id}`} className="flex items-center gap-2 text-[13px] hover:underline"><span className="font-mono text-[12px] text-muted">{f.code}</span><span className="flex-1">{f.title}</span><RiskBadge risk={f.severity} /></Link>
                )) : <p className="text-[13px] text-muted">You're all clear.</p>}
              </CardBody></Card>
              <Card><CardHeader title="Upcoming tests" /><CardBody className="space-y-1.5">
                {d.upcoming_tests.map((t: any) => (
                  <div key={t.code} className="flex items-center justify-between text-[13px]"><Link to={`/controls/${t.control_id}`} className="hover:underline"><span className="font-mono text-[12px] text-muted">{t.code}</span> {t.name}</Link><Badge tone={t.overdue ? "danger" : "neutral"}>{t.overdue ? "Overdue since " : ""}{fmtDate(t.due)}</Badge></div>
                ))}
              </CardBody></Card>
            </div>
          </div>
        )}
      </QueryView>
      {up && <UploadFor control={up.control} preset={up.preset} onClose={() => setUp(null)} />}
    </>
  );
}

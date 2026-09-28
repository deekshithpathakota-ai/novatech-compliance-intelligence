import * as React from "react";
import { Link, useSearchParams } from "react-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Upload } from "lucide-react";
import { toast } from "sonner";
import { EvidenceRequestDialog } from "@/components/app/EvidenceRequestDialog";
import { DataTable, EmptyState, KV, PageHeader, QueryView, StatusBadge, WhyButton } from "@/components/app";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Input, Label, Select } from "@/components/ui/input";
import { useAuth } from "@/hooks/useAuth";
import { api, ApiError } from "@/lib/api";
import { cn, fmtDate } from "@/lib/utils";
import type { ControlRow, EvidenceRow } from "@/types";

const FILTERS = ["", "VALID", "EXPIRING", "EXPIRED", "UNVERIFIED", "CONFLICTING", "MISSING", "REQUESTS"];

function Freshness({ e }: { e: EvidenceRow }) {
  const f = e.freshness;
  const tone = f.label === "EXPIRED" ? "bg-danger" : f.label === "EXPIRING" ? "bg-warning" : f.label === "AGING" ? "bg-subtle" : "bg-success";
  return (
    <div className="w-28">
      <div className="h-1.5 rounded-full bg-surface-2"><div className={cn("h-full rounded-full", tone)} style={{ width: `${Math.min(100, f.pct_elapsed)}%` }} /></div>
      <div className="mt-0.5 text-[10.5px] text-muted tabular">{f.remaining_days < 0 ? `expired ${-f.remaining_days}d ago` : `${f.remaining_days}d remaining`}</div>
    </div>
  );
}

function UploadDialog({ open, setOpen }: { open: boolean; setOpen: (b: boolean) => void }) {
  const controls = useQuery({ queryKey: ["controls", ""], queryFn: () => api.get<ControlRow[]>("/api/controls"), enabled: open });
  const qc = useQueryClient();
  const [busy, setBusy] = React.useState(false);
  const submit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const fd = new FormData(e.currentTarget);
    if (!(fd.get("file") as File)?.size) { toast.error("Choose a file to upload."); return; }
    setBusy(true);
    try {
      const r = await api.upload<any>("/api/evidence", fd);
      toast.success(`${r.evidence.code} uploaded — awaiting verification`);
      if (r.ingestion?.untrusted_instruction_detected) toast.warning("Untrusted instruction detected in document content — quarantined.");
      ["evidence", "controls", "nav-counts", "dashboard"].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
      setOpen(false);
    } catch (err) { toast.error((err as ApiError).message); } finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent title="Upload evidence" description="Stored with a SHA-256 hash, parsed through the secure ingestion pipeline, and marked unverified until reviewed.">
        <form onSubmit={submit} className="space-y-3">
          <div className="space-y-1"><Label htmlFor="ctl">Control</Label>
            <Select id="ctl" name="control_id" required className="w-full">{controls.data?.map((c) => <option key={c.id} value={c.id}>{c.code} — {c.name}</option>)}</Select></div>
          <div className="space-y-1"><Label htmlFor="nm">Evidence name</Label><Input id="nm" name="name" required maxLength={200} placeholder="Access Review Report — Q3 2026" /></div>
          <div className="space-y-1"><Label htmlFor="vd">Valid for (days)</Label><Input id="vd" name="valid_days" type="number" min={1} max={730} defaultValue={90} /></div>
          <div className="space-y-1"><Label htmlFor="fl">File (PDF, DOCX, TXT, CSV, XLSX)</Label><Input id="fl" name="file" type="file" className="pt-1.5" accept=".pdf,.docx,.txt,.md,.csv,.xlsx" /></div>
          <div className="flex justify-end gap-2 pt-2"><Button type="button" onClick={() => setOpen(false)}>Cancel</Button><Button variant="primary" type="submit" loading={busy}>Upload</Button></div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export default function Evidence() {
  const [p, setP] = useSearchParams();
  const status = p.get("status") ?? "";
  const focus = p.get("focus");
  const { can } = useAuth();
  const [up, setUp] = React.useState(false);
  const [req, setReq] = React.useState<any>(null);
  const requests = useQuery({ queryKey: ["evidence-requests"], queryFn: () => api.get<any[]>("/api/evidence-requests") });
  const q = useQuery({ queryKey: ["evidence"], queryFn: () => api.get<{ items: EvidenceRow[]; missing: any[] }>("/api/evidence") });
  const detail = useQuery({ queryKey: ["evidence", "d", focus], queryFn: () => api.get<any>(`/api/evidence/${focus}`), enabled: !!focus });
  const qc = useQueryClient();
  return (
    <>
      <PageHeader eyebrow="Evidence Intelligence" title="Evidence" description="Every evidence item with freshness, validity, verification and hash — linked to its control and source document."
        actions={can("EVIDENCE_UPLOAD") && <Button variant="primary" onClick={() => setUp(true)}><Upload className="h-4 w-4" />Upload evidence</Button>} />
      <QueryView q={q}>
        {(d) => {
          const counts: Record<string, number> = {};
          d.items.forEach((e) => (counts[e.status] = (counts[e.status] ?? 0) + 1));
          counts.MISSING = d.missing.length;
          counts.REQUESTS = requests.data?.filter((r) => r.status === "OPEN").length ?? 0;
          const rows = status ? d.items.filter((e) => e.status === status) : d.items;
          return (
            <>
              <div className="mb-4 flex flex-wrap gap-2">
                {FILTERS.map((f) => (
                  <button key={f || "all"} onClick={() => { const n = new URLSearchParams(p); f ? n.set("status", f) : n.delete("status"); setP(n); }}
                    className={cn("rounded-lg border px-3 py-1.5 text-[12.5px] font-medium cursor-pointer", status === f ? "border-accent bg-accent-soft text-accent" : "border-border bg-surface text-muted hover:text-foreground")}>
                    {f === "REQUESTS" ? "Requests" : f ? f.charAt(0) + f.slice(1).toLowerCase() : "All"} <span className="ml-1 tabular opacity-70">{f ? counts[f] ?? 0 : d.items.length}</span>
                  </button>
                ))}
              </div>
              {status === "REQUESTS" ? (
                <DataTable rows={requests.data ?? []} rowKey={(r: any) => r.id} empty={<EmptyState title="No evidence requests" />} columns={[
                  { key: "c", header: "Request", cell: (r: any) => <span className="font-mono text-[12px] text-muted">{r.code}</span> },
                  { key: "ctl", header: "Control", cell: (r: any) => <Link to={`/controls/${r.control.id}`} className="hover:underline">{r.control.code} {r.control.name}</Link> },
                  { key: "e", header: "Evidence required", cell: (r: any) => r.evidence_required },
                  { key: "to", header: "Recipient", cell: (r: any) => r.recipient },
                  { key: "by", header: "Requested by", hideOnMobile: true, cell: (r: any) => r.requested_by },
                  { key: "d", header: "Due", cell: (r: any) => <span className={r.overdue ? "text-danger font-medium" : ""}>{fmtDate(r.due_date)}</span> },
                  { key: "s", header: "Status", cell: (r: any) => <StatusBadge status={r.status === "FULFILLED" ? "COMPLETED" : r.overdue ? "OVERDUE" : r.status} /> },
                  { key: "x", header: "", cell: (r: any) => r.status === "OPEN" && can("EVIDENCE_REQUEST") ? <Button size="sm" variant="ghost" onClick={async () => { await api.post(`/api/evidence-requests/${r.id}/cancel`); requests.refetch(); }}>Cancel</Button> : null },
                ]} />
              ) : status === "MISSING" ? (
                d.missing.length ? (
                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
                    {d.missing.map((m) => (
                      <Card key={m.control_id} className="p-4">
                        <div className="flex items-center justify-between"><span className="font-mono text-[12px] text-muted">{m.control_code}</span><StatusBadge status="MISSING" /></div>
                        <div className="mt-1 text-[13.5px] font-medium">{m.control_name}</div>
                        <p className="mt-1 text-[12.5px] text-muted">No evidence has been submitted for this control. Owner: {m.owner ?? "unassigned"}.</p>
                        <div className="mt-2 flex items-center gap-3">
                          {can("EVIDENCE_REQUEST") && <Button size="sm" variant="primary" onClick={() => setReq(m)}>Request evidence</Button>}
                          <Link to={`/controls/${m.control_id}`} className="text-[12.5px] text-accent hover:underline">Open control →</Link>
                        </div>
                      </Card>
                    ))}
                  </div>
                ) : <EmptyState title="You're all clear." description="Every control has evidence on file." />
              ) : (
                <DataTable rows={rows} rowKey={(e) => e.id} onRowClick={(e) => { const n = new URLSearchParams(p); n.set("focus", String(e.id)); setP(n); }}
                  empty={<EmptyState title="No evidence in this state" />}
                  columns={[
                    { key: "c", header: "Evidence", cell: (e) => <span className="font-mono text-[12px] text-muted">{e.code}</span> },
                    { key: "n", header: "Name", cell: (e) => <div className="min-w-[200px] font-medium">{e.name}</div> },
                    { key: "ctl", header: "Control", cell: (e) => <span className="whitespace-nowrap"><span className="font-mono text-[12px] text-muted">{e.control_code}</span></span> },
                    { key: "fw", header: "Framework", hideOnMobile: true, cell: (e) => <span className="text-[12px] text-muted">{e.frameworks.join(", ")}</span> },
                    { key: "o", header: "Owner", hideOnMobile: true, cell: (e) => e.owner },
                    { key: "col", header: "Collected", hideOnMobile: true, cell: (e) => <span className="whitespace-nowrap">{fmtDate(e.collected_at)}</span> },
                    { key: "exp", header: "Expires", cell: (e) => <span className="whitespace-nowrap">{fmtDate(e.valid_until)}</span> },
                    { key: "f", header: "Freshness", cell: (e) => <Freshness e={e} /> },
                    { key: "v", header: "Verification", hideOnMobile: true, cell: (e) => <StatusBadge status={e.verification} /> },
                    { key: "s", header: "Status", cell: (e) => <StatusBadge status={e.status} /> },
                  ]} />
              )}
            </>
          );
        }}
      </QueryView>
      <UploadDialog open={up} setOpen={setUp} />
      {req && <EvidenceRequestDialog control={req} onClose={() => { setReq(null); requests.refetch(); }} />}
      <Dialog open={!!focus} onOpenChange={(o) => { if (!o) { const n = new URLSearchParams(p); n.delete("focus"); setP(n); } }}>
        <DialogContent side="right" title={detail.data ? `${detail.data.code} · ${detail.data.name}` : "Evidence"} description="Evidence detail and history">
          <QueryView q={detail}>
            {(e) => (
              <div className="space-y-4">
                <div className="flex flex-wrap items-center gap-2"><StatusBadge status={e.status} /><StatusBadge status={e.freshness.label} /><StatusBadge status={e.verification} /><WhyButton kind="evidence" code={e.code} /></div>
                <KV items={[
                  ["Control", <Link to={`/controls/${e.control_id}`} className="text-accent hover:underline">{e.control_code} — {e.control_name}</Link>],
                  ["Owner", e.owner], ["Source", e.source], ["Collected", fmtDate(e.collected_at)], ["Valid until", fmtDate(e.valid_until)],
                  ["Remaining", e.freshness.remaining_days < 0 ? `Expired ${-e.freshness.remaining_days} days ago` : `${e.freshness.remaining_days} days`],
                  ["Completeness", `${Math.round(e.completeness * 100)}%`],
                  ["Document", e.document ? <Link to={`/documents/${e.document.id}`} className="text-accent hover:underline">{e.document.name}{e.page ? ` · page ${e.page}` : ""}</Link> : "—"],
                  ["SHA-256", <span className="break-all font-mono text-[11px] text-muted">{e.sha256}</span>],
                ]} />
                {!!Object.keys(e.extracted ?? {}).length && (
                  <div><div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-subtle">Extracted facts</div>
                    <KV items={Object.entries(e.extracted).map(([k, v]) => [k.replace(/_/g, " "), String(v)])} /></div>
                )}
                <div><div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-subtle">Version history</div>
                  <ul className="space-y-1 text-[12.5px]">{e.versions.map((v: any) => <li key={v.version}>v{v.version} · {fmtDate(v.collected_at)} {v.note && <span className="text-muted">· {v.note}</span>}</li>)}</ul></div>
                {e.verification !== "verified" && can("FINDINGS_MANAGE") && (
                  <Button variant="success" onClick={async () => { await api.post(`/api/evidence/${e.id}/verify`); toast.success(`${e.code} verified`); qc.invalidateQueries({ queryKey: ["evidence"] }); }}>Mark as verified</Button>
                )}
              </div>
            )}
          </QueryView>
        </DialogContent>
      </Dialog>
    </>
  );
}

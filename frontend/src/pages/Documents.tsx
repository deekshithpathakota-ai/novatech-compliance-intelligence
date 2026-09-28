import * as React from "react";
import { useNavigate } from "react-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, Lock, Upload } from "lucide-react";
import { toast } from "sonner";
import { DataTable, PageHeader, QueryView, StatusBadge } from "@/components/app";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { useAuth } from "@/hooks/useAuth";
import { api, ApiError } from "@/lib/api";
import { fmtDate } from "@/lib/utils";

export function UploadDocument({ onDone }: { onDone?: () => void }) {
  const [report, setReport] = React.useState<any>(null);
  const [busy, setBusy] = React.useState(false);
  const ref = React.useRef<HTMLInputElement>(null);
  const qc = useQueryClient();
  const upload = async (f: File) => {
    const fd = new FormData();
    fd.append("file", f);
    setBusy(true);
    try {
      const r = await api.upload<any>("/api/documents", fd);
      setReport(r);
      if (r.untrusted_instruction_detected) toast.warning("Untrusted instruction detected in document content.");
      else toast.success(`${r.document.code} indexed`);
      ["documents", "security"].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
      onDone?.();
    } catch (e) { toast.error((e as ApiError).message); } finally { setBusy(false); if (ref.current) ref.current.value = ""; }
  };
  return (
    <>
      <input ref={ref} type="file" className="hidden" accept=".pdf,.docx,.txt,.md,.csv,.xlsx" onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} aria-label="Upload document" />
      <Button variant="primary" loading={busy} onClick={() => ref.current?.click()}><Upload className="h-4 w-4" />Upload document</Button>
      <Dialog open={!!report} onOpenChange={(o) => !o && setReport(null)}>
        <DialogContent title={report ? `Ingestion · ${report.document.name}` : ""} description="Parse → extract → OCR check → classify → injection scan → chunk → embed → store">
          {report && (
            <div className="space-y-3">
              {report.untrusted_instruction_detected && (
                <div className="flex gap-2 rounded-lg border border-danger/30 bg-danger-soft px-3 py-2.5 text-[13px] text-danger">
                  <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                  <div><b>Untrusted instruction detected in document content.</b> {report.quarantined} chunk(s) quarantined and never sent to the model. The document remains untrusted; a security event was recorded.</div>
                </div>
              )}
              <ol className="space-y-1.5">
                {report.pipeline.map((s: any) => (
                  <li key={s.step} className="flex items-start gap-2 text-[13px]">
                    {s.status === "warning" ? <AlertTriangle className="mt-0.5 h-3.5 w-3.5 text-warning" /> : <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 text-success" />}
                    <span className="w-[170px] shrink-0 font-medium">{s.step}</span><span className="text-muted">{s.detail}</span>
                  </li>
                ))}
              </ol>
              <div className="flex flex-wrap gap-1.5 text-[12px]"><StatusBadge status={report.document.status.toUpperCase()} /><Badge tone="neutral">{report.document.classification}</Badge><Badge tone="neutral">{report.document.document_type}</Badge><span className="font-mono text-muted">sha256 {report.document.sha256.slice(0, 16)}…</span></div>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}

export default function Documents() {
  const q = useQuery({ queryKey: ["documents"], queryFn: () => api.get<any[]>("/api/documents") });
  const nav = useNavigate();
  const { can } = useAuth();
  return (
    <>
      <PageHeader eyebrow="Document intelligence" title="Documents" description="Policies and evidence documents indexed for permission-filtered hybrid retrieval. Uploaded content is always treated as untrusted data."
        actions={can("DOCUMENTS_UPLOAD") && <UploadDocument />} />
      <QueryView q={q}>
        {(rows) => (
          <DataTable rows={rows} rowKey={(r) => r.id} onRowClick={(r) => nav(`/documents/${r.id}`)} columns={[
            { key: "c", header: "Document", cell: (r) => <span className="font-mono text-[12px] text-muted">{r.code}</span> },
            { key: "n", header: "Name", cell: (r) => <span className="flex items-center gap-2 font-medium">{!r.accessible && <Lock className="h-3.5 w-3.5 text-muted" />}{r.name.replace(/\.txt$/, "")}</span> },
            { key: "t", header: "Type", cell: (r) => <Badge tone="neutral">{r.type}</Badge> },
            { key: "cl", header: "Classification", cell: (r) => <Badge tone={r.classification === "restricted" ? "danger" : r.classification === "confidential" ? "warning" : "neutral"}>{r.classification}</Badge> },
            { key: "v", header: "Version", hideOnMobile: true, cell: (r) => `v${r.version}` },
            { key: "e", header: "Effective", hideOnMobile: true, cell: (r) => fmtDate(r.effective_date) },
            { key: "s", header: "Status", cell: (r) => r.security_flags?.some((f: any) => f.type === "prompt_injection") ? <Badge tone="danger">Untrusted instruction</Badge> : <StatusBadge status={r.status === "indexed" ? "ACTIVE" : r.status.toUpperCase()} /> },
          ]} />
        )}
      </QueryView>
    </>
  );
}

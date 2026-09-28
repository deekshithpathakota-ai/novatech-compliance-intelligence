import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ShieldCheck } from "lucide-react";
import { toast } from "sonner";
import { DataTable, PageHeader, QueryView, RiskBadge, StatusBadge } from "@/components/app";
import { Badge } from "@/components/ui/badge";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Select } from "@/components/ui/input";
import { useAuth } from "@/hooks/useAuth";
import { api } from "@/lib/api";
import { fmtDateTime, title } from "@/lib/utils";
import { UploadDocument } from "./Documents";

export default function Security() {
  const status = useQuery({ queryKey: ["security", "status"], queryFn: () => api.get<any>("/api/security/status") });
  const events = useQuery({ queryKey: ["security", "events"], queryFn: () => api.get<any[]>("/api/security/events") });
  const qc = useQueryClient();
  const { can } = useAuth();
  const setStatus = async (id: number, s: string) => {
    await api.post(`/api/security/events/${id}`, { status: s });
    toast.success(`Event → ${title(s)}`);
    ["security", "nav-counts"].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
  };
  return (
    <>
      <PageHeader eyebrow="Security Center" title="Security Center" description="Security controls that actually shape application behaviour, plus rule-based anomaly detection over the audit trail."
        actions={can("DOCUMENTS_UPLOAD") && <UploadDocument onDone={() => qc.invalidateQueries({ queryKey: ["security"] })} />} />
      <QueryView q={status}>
        {(s) => (
          <div className="mb-5 grid gap-5 lg:grid-cols-[minmax(0,1fr)_340px]">
            <Card><CardHeader title="Protections" description="Enforced in backend code" icon={<ShieldCheck className="h-4 w-4 text-success" />} /><CardBody className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              {s.protections.map((p: any) => (
                <div key={p.name} className="rounded-lg border border-border px-3 py-2.5">
                  <div className="flex items-center justify-between gap-2"><span className="text-[13px] font-medium">{p.name}</span><Badge tone={p.status === "ENFORCED" ? "success" : "accent"}>{p.status}</Badge></div>
                  <div className="mt-0.5 text-[12px] text-muted">{p.detail}</div>
                </div>
              ))}
            </CardBody></Card>
            <Card><CardHeader title="Last 30 days" description={s.label} /><CardBody className="space-y-2 text-[13px]">
              <div className="flex justify-between"><span className="text-muted">Open alerts</span><b className="text-danger tabular">{s.open_alerts}</b></div>
              <div className="flex justify-between"><span className="text-muted">Permission denials</span><b className="tabular">{s.denials_30d}</b></div>
              <div className="flex justify-between"><span className="text-muted">Flagged documents</span><b className="tabular">{s.flagged_documents}</b></div>
              {Object.entries(s.events_30d).map(([k, v]: any) => <div key={k} className="flex justify-between"><span className="text-muted">{title(k)}</span><span className="tabular">{v}</span></div>)}
              <div className="pt-2 text-[11.5px] text-subtle">Rules: {s.rules.map((r: any) => `${title(r.key)} (≥${r.threshold}/${r.window_min}m)`).join(" · ")}</div>
            </CardBody></Card>
          </div>
        )}
      </QueryView>
      <QueryView q={events}>
        {(rows) => (
          <DataTable rows={rows} rowKey={(r) => r.id} columns={[
            { key: "at", header: "Time", cell: (r) => <span className="whitespace-nowrap text-muted">{fmtDateTime(r.at)}</span> },
            { key: "t", header: "Event", cell: (r) => <span className="font-medium">{title(r.type)}</span> },
            { key: "d", header: "Description", cell: (r) => <div className="min-w-[240px]">{r.description}{r.details?.excerpts && <div className="mt-0.5 text-[11.5px] text-danger">“{r.details.excerpts[0]}”</div>}</div> },
            { key: "u", header: "User", hideOnMobile: true, cell: (r) => r.user ?? "—" },
            { key: "s", header: "Severity", cell: (r) => <RiskBadge risk={r.severity} /> },
            { key: "st", header: "Status", cell: (r) => can("SECURITY_MANAGE") ? (
              <Select aria-label="Event status" value={r.status} onChange={(e) => setStatus(r.id, e.target.value)} className="h-7 text-[12px]">
                {["OPEN", "INVESTIGATING", "RESOLVED"].map((x) => <option key={x} value={x}>{title(x)}</option>)}
              </Select>) : <StatusBadge status={r.status} /> },
          ]} />
        )}
      </QueryView>
    </>
  );
}

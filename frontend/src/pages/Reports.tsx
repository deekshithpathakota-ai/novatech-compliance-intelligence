import * as React from "react";
import { useNavigate } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { FileBarChart } from "lucide-react";
import { toast } from "sonner";
import { DataTable, EmptyState, PageHeader, QueryView } from "@/components/app";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/hooks/useAuth";
import { api, ApiError } from "@/lib/api";
import { fmtDateTime } from "@/lib/utils";

export default function Reports() {
  const q = useQuery({ queryKey: ["reports"], queryFn: () => api.get<any[]>("/api/reports") });
  const nav = useNavigate();
  const { can } = useAuth();
  const [busy, setBusy] = React.useState(false);
  const gen = async () => {
    setBusy(true);
    try { const r = await api.post<any>("/api/reports/audit-readiness"); nav(`/reports/${r.id}`); }
    catch (e) { toast.error((e as ApiError).message); } finally { setBusy(false); }
  };
  return (
    <>
      <PageHeader eyebrow="Reports" title="Audit readiness reports" description="Evidence-backed reports generated from live state — exportable as a designed PDF or CSV."
        actions={can("REPORTS_GENERATE") && <Button variant="primary" loading={busy} onClick={gen}><FileBarChart className="h-4 w-4" />Generate Audit Readiness Report</Button>} />
      <QueryView q={q}>
        {(rows) => (
          <DataTable rows={rows} rowKey={(r) => r.id} onRowClick={(r) => nav(`/reports/${r.id}`)}
            empty={<EmptyState title="No reports yet" description="Generate one here or ask the Compliance Agent." />}
            columns={[
              { key: "c", header: "Report", cell: (r) => <span className="font-mono text-[12px] text-muted">{r.code}</span> },
              { key: "t", header: "Title", cell: (r) => <span className="font-medium">{r.title}</span> },
              { key: "r", header: "Readiness", cell: (r) => r.readiness != null ? `${r.readiness}%` : "—" },
              { key: "src", header: "Source", cell: (r) => r.agent_run_id ? "Compliance Agent" : "Manual" },
              { key: "d", header: "Generated", cell: (r) => fmtDateTime(r.created_at) },
            ]} />
        )}
      </QueryView>
    </>
  );
}

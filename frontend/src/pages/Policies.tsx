import * as React from "react";
import { Link } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { DataTable, PageHeader, QueryView, StatusBadge } from "@/components/app";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { api } from "@/lib/api";
import { fmtDate } from "@/lib/utils";

export default function Policies() {
  const q = useQuery({ queryKey: ["policies"], queryFn: () => api.get<any[]>("/api/policies") });
  const [open, setOpen] = React.useState<any>(null);
  const v = useQuery({ queryKey: ["policy-versions", open?.id], queryFn: () => api.get<any[]>(`/api/policies/${open.id}/versions`), enabled: !!open });
  return (
    <>
      <PageHeader eyebrow="Policy memory" title="Policies" description="Current and previous policy versions, review cadence and the controls each policy governs." />
      <QueryView q={q}>
        {(rows) => (
          <DataTable rows={rows} rowKey={(r) => r.id} onRowClick={setOpen} columns={[
            { key: "c", header: "Policy", cell: (r) => <span className="font-mono text-[12px] text-muted">{r.code}</span> },
            { key: "n", header: "Name", cell: (r) => <span className="font-medium">{r.name}</span> },
            { key: "v", header: "Version", cell: (r) => `v${r.version}` },
            { key: "r", header: "Last reviewed", hideOnMobile: true, cell: (r) => fmtDate(r.last_reviewed) },
            { key: "nx", header: "Next review", cell: (r) => <span className={r.review_overdue ? "text-danger font-medium" : ""}>{fmtDate(r.next_review)}</span> },
            { key: "ctl", header: "Controls", hideOnMobile: true, cell: (r) => <div className="flex flex-wrap gap-1">{r.controls.map((c: string) => <Badge key={c} tone="neutral">{c}</Badge>)}</div> },
            { key: "s", header: "Status", cell: (r) => <StatusBadge status={r.status} /> },
          ]} />
        )}
      </QueryView>
      <Dialog open={!!open} onOpenChange={(o) => !o && setOpen(null)}>
        <DialogContent side="right" title={open ? `${open.code} · ${open.name}` : ""} description="Version history">
          <QueryView q={v}>
            {(vs) => (
              <div className="space-y-2 text-[13px]">
                {[...vs].reverse().map((x, i) => (
                  <Card key={x.version} className="px-3 py-2.5">
                    <div className="flex items-center justify-between"><b>v{x.version}</b>{i === 0 ? <Badge tone="success">Current</Badge> : <Badge tone="neutral">Previous</Badge>}</div>
                    <div className="text-muted">Effective {fmtDate(x.effective_date)}</div>
                    <div className="mt-1">{x.change_summary}</div>
                  </Card>
                ))}
                {open?.document_id && <Link to={`/documents/${open.document_id}`} className="text-accent hover:underline">Open policy document →</Link>}
              </div>
            )}
          </QueryView>
        </DialogContent>
      </Dialog>
    </>
  );
}

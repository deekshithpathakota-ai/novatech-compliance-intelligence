import * as React from "react";
import { Link } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { DataTable, PageHeader, QueryView, StatusBadge } from "@/components/app";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";
import { cn, fmtDate } from "@/lib/utils";

export default function Requirements() {
  const fws = useQuery({ queryKey: ["frameworks"], queryFn: () => api.get<any[]>("/api/frameworks") });
  const [fw, setFw] = React.useState("ISO27001");
  const [search, setSearch] = React.useState("");
  const [open, setOpen] = React.useState<number | null>(null);
  const q = useQuery({ queryKey: ["requirements", fw], queryFn: () => api.get<any[]>(`/api/requirements?framework=${fw}`) });
  const d = useQuery({ queryKey: ["requirement", open], queryFn: () => api.get<any>(`/api/requirements/${open}`), enabled: !!open });
  return (
    <>
      <PageHeader eyebrow="Compliance knowledge model" title="Requirements" description="Framework → requirement → control mapping. All wording is synthetic — Prototype / Demonstration Mapping, not official standard text." />
      <QueryView q={fws}>
        {(list) => (
          <div className="mb-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {list.map((f) => (
              <button key={f.code} onClick={() => setFw(f.code)} className={cn("rounded-card border p-4 text-left transition-colors cursor-pointer", fw === f.code ? "border-accent bg-accent-soft" : "border-border bg-surface hover:bg-surface-2")}>
                <div className="text-[13.5px] font-semibold">{f.name}</div>
                <div className="mt-2 flex gap-3 text-[12px] text-muted"><span><b className="text-foreground tabular">{f.requirements}</b> requirements</span><span><b className="text-foreground tabular">{f.controls}</b> controls</span></div>
                <div className="mt-1 text-[12px] text-muted">{f.mapped}/{f.requirements} mapped</div>
                {f.is_demo_mapping && <Badge tone="accent" className="mt-2 normal-case tracking-normal">Prototype / Demonstration Mapping</Badge>}
              </button>
            ))}
          </div>
        )}
      </QueryView>
      <Input placeholder="Filter requirements…" value={search} onChange={(e) => setSearch(e.target.value)} className="mb-3 max-w-sm" aria-label="Filter requirements" />
      <QueryView q={q}>
        {(rows) => (
          <DataTable rows={rows.filter((r) => (r.code + r.title).toLowerCase().includes(search.toLowerCase()))} rowKey={(r) => r.id} onRowClick={(r) => setOpen(r.id)}
            columns={[
              { key: "c", header: "Requirement", cell: (r) => <span className="font-mono text-[12px] text-muted whitespace-nowrap">{r.code}</span> },
              { key: "t", header: "Title", cell: (r) => <span className="font-medium">{r.title}</span> },
              { key: "cat", header: "Category", hideOnMobile: true, cell: (r) => <span className="text-muted">{r.category}</span> },
              { key: "v", header: "Version", cell: (r) => `v${r.version}` },
              { key: "ctl", header: "Mapped controls", cell: (r) => r.controls.length ? <div className="flex flex-wrap gap-1">{r.controls.map((c: any) => <Link key={c.id} to={`/controls/${c.id}`} onClick={(e) => e.stopPropagation()}><Badge tone={c.status === "PASS" ? "success" : c.status === "AT_RISK" ? "warning" : "danger"}>{c.code}</Badge></Link>)}</div> : <Badge tone="danger">No mapped control</Badge> },
              { key: "s", header: "Status", cell: (r) => <StatusBadge status={r.status === "changed" ? "CHANGED" : "ACTIVE"} /> },
            ]} />
        )}
      </QueryView>
      <Dialog open={!!open} onOpenChange={(o) => !o && setOpen(null)}>
        <DialogContent side="right" title={d.data ? `${d.data.code} · ${d.data.title}` : "Requirement"} description={d.data?.label}>
          <QueryView q={d}>
            {(r) => (
              <div className="space-y-4 text-[13px]">
                <p>{r.description}</p>
                <div><div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-subtle">Version history</div>
                  {r.versions.map((v: any) => <Card key={v.version} className="mb-2 px-3 py-2"><div className="font-medium">v{v.version} · effective {fmtDate(v.effective_date)}</div><div className="text-muted">{v.change_summary}</div></Card>)}</div>
                <div><div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-subtle">Mapped controls</div>
                  {r.controls.length ? r.controls.map((c: any) => <Link key={c.id} to={`/controls/${c.id}`} className="flex items-center justify-between border-b border-border py-2 hover:underline"><span><span className="font-mono text-muted">{c.code}</span> {c.name}</span><StatusBadge status={c.status} /></Link>)
                    : <p className="text-danger">Requirement currently has no mapped control.</p>}</div>
              </div>
            )}
          </QueryView>
        </DialogContent>
      </Dialog>
    </>
  );
}

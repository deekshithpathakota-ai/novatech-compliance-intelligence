import * as React from "react";
import { useQuery } from "@tanstack/react-query";
import { Brain, Search } from "lucide-react";
import { EmptyState, KV, PageHeader, QueryView, StatusBadge } from "@/components/app";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";
import { cn, fmtDate, title } from "@/lib/utils";

export default function Memory() {
  const [cat, setCat] = React.useState("");
  const [q, setQ] = React.useState("");
  const [term, setTerm] = React.useState("");
  const [open, setOpen] = React.useState<number | null>(null);
  const qs = new URLSearchParams();
  if (cat) qs.set("category", cat);
  if (term) qs.set("q", term);
  const data = useQuery({ queryKey: ["memory", cat, term], queryFn: () => api.get<any>(`/api/memory?${qs}&limit=150`) });
  const item = useQuery({ queryKey: ["memory-item", open], queryFn: () => api.get<any>(`/api/memory/${open}`), enabled: !!open });
  return (
    <>
      <PageHeader eyebrow="Persistent audit memory" title="Agent memory" description="What happened, why, what was done, whether it worked — and why it matters today. Written by audits, remediation, verification and the agent itself." />
      <form onSubmit={(e) => { e.preventDefault(); setTerm(q); }} className="mb-4 flex max-w-xl gap-2">
        <div className="relative flex-1"><Search className="absolute left-3 top-2.5 h-4 w-4 text-subtle" /><Input className="pl-9" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Have we seen this issue before? e.g. “access review overdue”" aria-label="Search memory" /></div>
      </form>
      <QueryView q={data}>
        {(d) => (
          <>
            <div className="mb-4 flex flex-wrap gap-2">
              <button onClick={() => setCat("")} className={cn("rounded-lg border px-3 py-1.5 text-[12.5px] cursor-pointer", !cat ? "border-accent bg-accent-soft text-accent" : "border-border text-muted")}>All</button>
              {d.categories.map((c: string) => (
                <button key={c} onClick={() => setCat(c)} className={cn("rounded-lg border px-3 py-1.5 text-[12.5px] cursor-pointer", cat === c ? "border-accent bg-accent-soft text-accent" : "border-border text-muted")}>
                  {title(c)} <span className="tabular opacity-70">{d.counts[c] ?? 0}</span>
                </button>
              ))}
            </div>
            {d.records.length ? (
              <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
                {d.records.map((m: any) => (
                  <button key={m.id} onClick={() => setOpen(m.id)} className="text-left">
                    <Card className="h-full p-4 transition-shadow hover:shadow-pop">
                      <div className="flex flex-wrap items-center gap-2 text-[12px]">
                        <Badge tone={m.category === "BEHAVIOR" ? "danger" : "accent"}>{m.category}</Badge>
                        {m.subject_code && <span className="font-mono text-muted">{m.subject_code}</span>}
                        <span className="text-muted">{fmtDate(m.occurred_at)}</span>
                        {m.written_by === "agent" && <Badge tone="info">written by agent</Badge>}
                        <span className="ml-auto flex gap-1">{m.outcome && <StatusBadge status={m.outcome.toUpperCase().replace(/ /g, "_")} />}{m.verification && <StatusBadge status={m.verification} />}</span>
                      </div>
                      <div className="mt-2 text-[13px]">{m.summary}</div>
                      {m.current_relevance && <div className="mt-2 text-[12.5px] text-accent"><Brain className="mr-1 inline h-3.5 w-3.5" />Current relevance: {m.current_relevance}</div>}
                    </Card>
                  </button>
                ))}
              </div>
            ) : <EmptyState title="No memory records match" />}
          </>
        )}
      </QueryView>
      <Dialog open={!!open} onOpenChange={(o) => !o && setOpen(null)}>
        <DialogContent side="right" title="Memory record" description="Why is this past result relevant?">
          <QueryView q={item}>
            {(m) => (
              <div className="space-y-4 text-[13px]">
                <p className="text-[14px] font-medium">“{m.summary}”</p>
                <KV items={[["Category", m.category], ["Subject", m.subject_code ?? "—"], ["Source", `${m.source_label} (${m.source_type})`], ["Date", fmtDate(m.occurred_at)],
                  ["Outcome", m.outcome ?? "—"], ["Verification", m.verification ?? "—"], ["Written by", m.written_by], ["Current relevance", <span className="text-accent">{m.current_relevance ?? "—"}</span>]]} />
                {!!m.related.length && <div><div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-subtle">Related memory</div>
                  <ul className="space-y-1.5">{m.related.map((r: any) => <li key={r.id} className="rounded-lg bg-surface-2 px-3 py-2"><Badge tone="neutral">{r.category}</Badge> <span className="text-muted">{fmtDate(r.occurred_at)}</span> — {r.summary}</li>)}</ul></div>}
              </div>
            )}
          </QueryView>
        </DialogContent>
      </Dialog>
    </>
  );
}

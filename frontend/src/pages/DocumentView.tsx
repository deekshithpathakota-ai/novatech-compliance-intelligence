import { Link, useParams } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, ShieldAlert } from "lucide-react";
import { KV, PageHeader, QueryView } from "@/components/app";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { api } from "@/lib/api";
import { cn, fmtDate } from "@/lib/utils";

export default function DocumentView() {
  const { id } = useParams();
  const q = useQuery({ queryKey: ["document", id], queryFn: () => api.get<any>(`/api/documents/${id}`) });
  return (
    <QueryView q={q}>
      {(d) => {
        const pages = Array.from(new Set(d.chunks.map((c: any) => c.page))) as number[];
        return (
          <>
            <PageHeader eyebrow={<Link to="/documents" className="hover:underline">Documents · {d.code}</Link>} title={d.name.replace(/\.txt$/, "")}
              description={`${d.type} · ${d.classification} · v${d.version} · effective ${fmtDate(d.effective_date)}`} />
            <div className="grid grid-cols-1 gap-5 lg:grid-cols-[minmax(0,1fr)_300px]">
              <div className="space-y-4">
                {d.security_flags?.map((f: any, i: number) => (
                  <div key={i} className={cn("flex gap-2 rounded-card border px-4 py-3 text-[13px]", f.type === "prompt_injection" ? "border-danger/30 bg-danger-soft text-danger" : "border-warning/30 bg-warning-soft text-warning")}>
                    {f.type === "prompt_injection" ? <ShieldAlert className="mt-0.5 h-4 w-4" /> : <AlertTriangle className="mt-0.5 h-4 w-4" />}
                    <div><b>{f.notice}</b>{f.rules && <div className="opacity-90">Rules: {f.rules.join(", ")} · quarantined chunks: {f.chunks.length}</div>}{f.detected && <div className="opacity-90">Masked: {f.detected.join(", ")}</div>}</div>
                  </div>
                ))}
                {pages.map((p) => (
                  <Card key={p} className="p-5">
                    <div className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-subtle">Page {p}</div>
                    {d.chunks.filter((c: any) => c.page === p).map((c: any) => (
                      <div key={c.index} className={cn("mb-3 last:mb-0", c.quarantined && "rounded-lg border border-dashed border-danger/40 bg-danger-soft/40 p-3")}>
                        {c.section && <div className="text-[13px] font-semibold">{c.section}</div>}
                        <p className={cn("whitespace-pre-line text-[13px] leading-relaxed", c.quarantined ? "italic text-danger" : "text-foreground")}>{c.content}</p>
                      </div>
                    ))}
                  </Card>
                ))}
              </div>
              <Card className="h-fit p-4">
                <KV items={[["Classification", <Badge tone="neutral">{d.classification}</Badge>], ["Framework", d.framework ?? "—"], ["Pages", d.pages], ["Source", d.source], ["Uploaded", fmtDate(d.uploaded_at)],
                  ["SHA-256", <span className="break-all font-mono text-[11px] text-muted">{d.sha256}</span>]]} />
                <p className="mt-3 text-[11.5px] text-subtle">Document content is untrusted data. It is never treated as instructions by the agent.</p>
              </Card>
            </div>
          </>
        );
      }}
    </QueryView>
  );
}

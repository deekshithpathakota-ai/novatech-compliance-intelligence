import * as React from "react";
import { Link, useParams } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, ChevronLeft, ChevronRight, ClipboardList, FileCheck2, FlaskConical, Pause, Play, ShieldAlert, ThumbsUp, Wrench, Zap } from "lucide-react";
import { PageHeader, QueryView, StatusBadge } from "@/components/app";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { cn, fmtDate, title } from "@/lib/utils";
import { api } from "@/lib/api";

const ICON: Record<string, React.ElementType> = { scope: ClipboardList, tests: FlaskConical, evidence: FileCheck2, findings: ShieldAlert,
  remediation: Wrench, approval: ThumbsUp, action: Zap, verification: CheckCircle2, result: CheckCircle2 };
const TONE: Record<string, string> = { neutral: "border-border-strong", success: "border-success", danger: "border-danger", warning: "border-warning", info: "border-accent" };

export default function AuditReplay() {
  const { id } = useParams();
  const q = useQuery({ queryKey: ["replay", id], queryFn: () => api.get<any>(`/api/audits/${id}/replay`) });
  const [i, setI] = React.useState(0);
  const [playing, setPlaying] = React.useState(false);
  const n = q.data?.frames.length ?? 0;
  React.useEffect(() => {
    if (!playing) return;
    if (i >= n - 1) { setPlaying(false); return; }
    const t = setTimeout(() => setI((x) => x + 1), 1400);
    return () => clearTimeout(t);
  }, [playing, i, n]);
  return (
    <QueryView q={q}>
      {(d) => {
        const f = d.frames[i];
        const Icon = ICON[f.kind] ?? ClipboardList;
        return (
          <>
            <PageHeader eyebrow={<Link to={`/audits/${d.audit.id}`} className="hover:underline">Audits · {d.audit.code}</Link>} title={`Replay · ${d.audit.name}`}
              description={`${d.audit.framework} · ${fmtDate(d.audit.start)} → ${fmtDate(d.audit.end)} · ${d.audit.outcome ?? title(d.audit.status)}`}
              actions={<>
                <Button size="icon" onClick={() => setI(Math.max(0, i - 1))} aria-label="Previous"><ChevronLeft className="h-4 w-4" /></Button>
                <Button variant="primary" onClick={() => { if (i >= n - 1) setI(0); setPlaying(!playing); }}>{playing ? <><Pause className="h-4 w-4" />Pause</> : <><Play className="h-4 w-4" />Replay</>}</Button>
                <Button size="icon" onClick={() => setI(Math.min(n - 1, i + 1))} aria-label="Next"><ChevronRight className="h-4 w-4" /></Button>
              </>} />
            <div className="mb-4 grid grid-cols-3 gap-2 sm:grid-cols-5 lg:grid-cols-9">
              {Object.entries(d.stats).map(([k, v]: any) => <Card key={k} className="px-3 py-2"><div className="text-[11px] text-muted">{title(k)}</div><div className="text-[17px] font-semibold tabular">{v}</div></Card>)}
            </div>
            <div className="grid grid-cols-1 gap-5 lg:grid-cols-[300px_minmax(0,1fr)]">
              <ol className="space-y-1" aria-label="Replay timeline">
                {d.frames.map((fr: any, k: number) => {
                  const I = ICON[fr.kind] ?? ClipboardList;
                  return (
                    <li key={k}>
                      <button onClick={() => { setPlaying(false); setI(k); }} className={cn("flex w-full items-start gap-2 rounded-lg px-2.5 py-2 text-left text-[12.5px] transition-colors cursor-pointer",
                        k === i ? "bg-accent-soft text-foreground" : k < i ? "text-foreground hover:bg-surface-2" : "text-subtle hover:bg-surface-2")}>
                        <I className={cn("mt-0.5 h-3.5 w-3.5 shrink-0", k <= i ? "text-accent" : "text-subtle")} />
                        <span className="min-w-0"><span className="block truncate font-medium">{fr.title}</span><span className="text-[11px] text-muted">{title(fr.kind)} · {fmtDate(fr.at)}</span></span>
                      </button>
                    </li>
                  );
                })}
              </ol>
              <Card key={i} className={cn("nt-in border-l-[3px] p-5", TONE[f.tone])}>
                <div className="flex items-center gap-2 text-[11.5px] font-semibold uppercase tracking-wider text-muted"><Icon className="h-4 w-4" />Step {i + 1} of {n} · {title(f.kind)} · {fmtDate(f.at)}</div>
                <div className="mt-2 text-[17px] font-semibold">{f.title}</div>
                <ul className="mt-4 max-h-[60vh] divide-y divide-border overflow-y-auto scrollbar-thin">
                  {f.items.map((it: any, k: number) => (
                    <li key={k} className="flex items-center gap-3 py-2 text-[13px]">
                      <span className="w-[120px] shrink-0 font-mono text-[12px] text-muted">{it.code}</span>
                      <span className="min-w-0 flex-1">{it.id ? <Link to={`/findings/${it.id}`} className="hover:underline">{it.label}</Link> : it.label}</span>
                      {it.status && <StatusBadge status={it.status} />}
                    </li>
                  ))}
                </ul>
              </Card>
            </div>
          </>
        );
      }}
    </QueryView>
  );
}

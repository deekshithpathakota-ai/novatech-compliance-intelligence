import * as React from "react";
import { useSearchParams } from "react-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ArrowUp, Bot, Brain, CheckCircle2, ChevronDown, Circle, CircleDot, Loader2, MessageSquarePlus, Wrench, XCircle } from "lucide-react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Textarea } from "@/components/ui/input";
import { useAuth } from "@/hooks/useAuth";
import { api, ApiError, streamRun } from "@/lib/api";
import { cn, fmtDateTime, relDays, title } from "@/lib/utils";
import type { AgentRun, AgentStep } from "@/types";
import { CardView, type CardCtx } from "./Cards";

type Msg = { id: number | string; role: "user" | "assistant"; content: string; cards: any[]; run_id: number | null; at: string };
type RunState = { run?: AgentRun; steps: AgentStep[]; live: boolean };

const PHASES = ["UNDERSTAND", "PLAN", "RETRIEVE", "ASSESS", "DETECT", "INVESTIGATE", "REMEDIATE", "VERIFY", "REMEMBER"];

// ------------------------------------------------------------------ live activity
function StepIcon({ s }: { s: AgentStep["status"] }) {
  if (s === "running") return <CircleDot className="h-3.5 w-3.5 text-accent nt-pulse" />;
  if (s === "warning") return <AlertTriangle className="h-3.5 w-3.5 text-warning" />;
  if (s === "failed") return <XCircle className="h-3.5 w-3.5 text-danger" />;
  return <CheckCircle2 className="h-3.5 w-3.5 text-success" />;
}
export function ActivityPanel({ steps, live }: { steps: AgentStep[]; live: boolean }) {
  const [open, setOpen] = React.useState<number | null>(null);
  const visible = steps.filter((s) => s.event !== "plan.created");
  return (
    <div className="rounded-card border border-border bg-surface shadow-card" aria-live="polite">
      <div className="flex items-center justify-between border-b border-border px-4 py-2.5">
        <div className="flex items-center gap-2 text-[12px] font-semibold uppercase tracking-wider text-muted"><Bot className="h-3.5 w-3.5 text-accent" />Compliance Agent · activity</div>
        {live ? <Badge tone="accent" dot className="nt-pulse">Working</Badge> : <Badge tone="neutral">{visible.length} steps</Badge>}
      </div>
      <ol className="divide-y divide-border">
        {visible.map((s) => (
          <li key={s.id} className="nt-in">
            <button onClick={() => setOpen(open === s.id ? null : s.id)} className="flex w-full items-center gap-2.5 px-4 py-2 text-left text-[13px] hover:bg-surface-2 cursor-pointer" aria-expanded={open === s.id}>
              <StepIcon s={s.status} />
              <span className={cn("flex-1", s.status === "running" && "text-accent font-medium")}>{s.title}</span>
              {s.tool && <span className="hidden font-mono text-[11px] text-subtle sm:inline">{s.tool}</span>}
              <ChevronDown className={cn("h-3.5 w-3.5 text-subtle transition-transform", open === s.id && "rotate-180")} />
            </button>
            {open === s.id && (
              <div className="grid grid-cols-2 gap-x-4 gap-y-1 bg-surface-2/60 px-4 py-2.5 pl-10 text-[12px] sm:grid-cols-5">
                <div><div className="text-muted">Event</div><div className="font-mono">{s.event}</div></div>
                <div><div className="text-muted">Tool</div><div className="font-mono">{s.tool ?? "—"}</div></div>
                <div><div className="text-muted">Duration</div><div className="tabular">{s.duration_ms} ms</div></div>
                <div><div className="text-muted">Evidence</div><div className="tabular">{s.evidence_count}</div></div>
                <div><div className="text-muted">Status</div><div>{title(s.status)}</div></div>
                {Object.keys(s.detail ?? {}).length > 0 && (
                  <pre className="col-span-full mt-1 max-h-40 overflow-auto rounded-md bg-surface p-2 font-mono text-[11px] text-muted scrollbar-thin">{JSON.stringify(s.detail, null, 2)}</pre>
                )}
              </div>
            )}
          </li>
        ))}
        {live && !visible.some((s) => s.status === "running") && (
          <li className="flex items-center gap-2.5 px-4 py-2 text-[13px] text-muted"><Loader2 className="h-3.5 w-3.5 animate-spin" />Understanding objective…</li>
        )}
      </ol>
    </div>
  );
}

// ------------------------------------------------------------------ right context panel
function ContextPanel({ state }: { state?: RunState }) {
  const run = state?.run;
  const steps = state?.steps ?? [];
  const plan = run?.plan ?? (steps.find((s) => s.event === "plan.created")?.detail?.steps as AgentRun["plan"]) ?? [];
  const objective = run?.objective ?? steps.find((s) => s.event === "plan.created")?.detail?.objective;
  const done = new Set<number>([...(run?.plan_done ?? []), ...steps.filter((s) => s.status !== "running" && s.detail?._plan).map((s) => s.detail._plan as number)]);
  const current = steps.filter((s) => s.status === "running").at(-1);
  const tools = Array.from(new Set(steps.map((s) => s.tool).filter(Boolean))) as string[];
  const evidence = steps.reduce((a, s) => a + (s.evidence_count || 0), 0);
  const phaseSeen = new Set(steps.map((s) => s.phase));
  const approvals = (run?.cards ?? []).filter((c) => c.type === "approval");
  const risk = (run?.cards ?? []).find((c) => c.type === "summary_metrics")?.items;
  if (!state) {
    return (
      <Card className="p-5 text-[13px] text-muted">
        <div className="mb-2 text-[12px] font-semibold uppercase tracking-wider text-subtle">Agent context</div>
        Ask a question or give the agent an objective. Its plan, current step, tools, evidence and approvals appear here as it works.
      </Card>
    );
  }
  return (
    <Card className="divide-y divide-border">
      <section className="p-4">
        <div className="text-[11px] font-semibold uppercase tracking-wider text-subtle">Objective</div>
        <div className="mt-1 text-[13.5px] font-medium">{objective ?? "Understanding objective…"}</div>
        <div className="mt-3 flex flex-wrap gap-1">
          {PHASES.map((p) => <span key={p} className={cn("rounded px-1.5 py-0.5 text-[10px] font-semibold tracking-wide", phaseSeen.has(p) ? "bg-accent-soft text-accent" : "bg-surface-2 text-subtle")}>{p}</span>)}
        </div>
      </section>
      <section className="p-4">
        <div className="text-[11px] font-semibold uppercase tracking-wider text-subtle">Plan</div>
        <ol className="mt-2 space-y-1.5">
          {plan.map((p) => {
            const isDone = done.has(p.id) || (run && run.status !== "RUNNING" && !state.live);
            const isCur = !isDone && current && plan.findIndex((x) => !done.has(x.id)) === plan.indexOf(p);
            return (
              <li key={p.id} className="flex items-start gap-2 text-[12.5px]">
                {isDone ? <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-success" /> : isCur ? <CircleDot className="mt-0.5 h-3.5 w-3.5 shrink-0 text-accent nt-pulse" /> : <Circle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-subtle" />}
                <span className={cn(isDone ? "text-foreground" : isCur ? "font-medium text-accent" : "text-muted")}>{p.title}</span>
              </li>
            );
          })}
        </ol>
      </section>
      <section className="p-4 text-[12.5px]">
        <div className="text-[11px] font-semibold uppercase tracking-wider text-subtle">Current step</div>
        <div className="mt-1">{current?.title ?? (state.live ? "Starting…" : run ? title(run.status) : "—")}</div>
        <div className="mt-3 grid grid-cols-2 gap-2">
          <div className="rounded-lg bg-surface-2 px-3 py-2"><div className="text-muted">Tools used</div><div className="text-[16px] font-semibold tabular">{tools.length}</div></div>
          <div className="rounded-lg bg-surface-2 px-3 py-2"><div className="text-muted">Evidence checked</div><div className="text-[16px] font-semibold tabular">{evidence}</div></div>
        </div>
        {!!tools.length && <div className="mt-2 flex flex-wrap gap-1">{tools.map((t) => <span key={t} className="rounded bg-surface-2 px-1.5 py-0.5 font-mono text-[10.5px] text-muted">{t}</span>)}</div>}
      </section>
      {risk && (
        <section className="p-4 text-[12.5px]">
          <div className="text-[11px] font-semibold uppercase tracking-wider text-subtle">Risk</div>
          <div className="mt-2 space-y-1">{risk.slice(0, 6).map((m: any) => <div key={m.label} className="flex justify-between"><span className="text-muted">{m.label}</span><b className="tabular">{m.value}</b></div>)}</div>
        </section>
      )}
      <section className="p-4 text-[12.5px]">
        <div className="text-[11px] font-semibold uppercase tracking-wider text-subtle">Approvals</div>
        {approvals.length ? approvals.map((a: any) => <div key={a.approval.id} className="mt-1.5 flex items-center justify-between gap-2"><span className="truncate">{a.approval.title}</span><Badge tone="warning">{a.approval.risk_level}</Badge></div>)
          : <div className="mt-1 text-muted">None required</div>}
      </section>
      <section className="p-4 text-[11.5px] text-subtle">
        Engine: {run?.engine === "openai-agents" ? `OpenAI Agents SDK · ${run.model}` : "Deterministic engine (no LLM key configured)"}{run?.duration_ms ? ` · ${(run.duration_ms / 1000).toFixed(1)}s` : ""}
        <div className="mt-1">Shows action summaries only — never private chain-of-thought.</div>
      </section>
    </Card>
  );
}

// ------------------------------------------------------------------ page
const STARTERS = [
  { label: "Prepare NovaTech for our upcoming ISO 27001-style audit.", icon: "🎯" },
  { label: "Why is Control C-017 considered high risk?", icon: "?" },
  { label: "Show me recurring compliance findings.", icon: "↻" },
  { label: "What changed since the previous audit?", icon: "Δ" },
];

export default function AgentPage() {
  const { user } = useAuth();
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();
  const convId = params.get("c") ? Number(params.get("c")) : null;
  const [input, setInput] = React.useState("");
  const [pending, setPending] = React.useState<Msg[]>([]);
  const [runs, setRuns] = React.useState<Record<number, RunState>>({});
  const [focusRun, setFocusRun] = React.useState<number | null>(null);
  const [showHistory, setShowHistory] = React.useState(false);
  const bottom = React.useRef<HTMLDivElement>(null);
  const sentQ = React.useRef(false);

  const convs = useQuery({ queryKey: ["conversations"], queryFn: () => api.get<{ id: number; title: string; updated_at: string; messages: number }[]>("/api/conversations") });
  const msgs = useQuery({ queryKey: ["messages", convId], queryFn: () => api.get<Msg[]>(`/api/conversations/${convId}/messages`), enabled: !!convId });

  const attach = React.useCallback((runId: number) => {
    setFocusRun(runId);
    setRuns((r) => ({ ...r, [runId]: { steps: [], live: true } }));
    let finished = false;
    // Polling fallback: used when streaming is unavailable, or when a proxy closes the stream before the run ends.
    const poll = async () => {
      try {
        const r = await api.get<AgentRun>(`/api/agent/runs/${runId}`);
        const st = await api.get<{ steps: AgentStep[] }>(`/api/agent/runs/${runId}/steps`);
        const live = r.status === "RUNNING";
        setRuns((x) => ({ ...x, [runId]: { run: r, steps: st.steps, live } }));
        if (live) setTimeout(poll, 800);
        else { setPending([]); qc.invalidateQueries({ queryKey: ["messages"] }); }
      } catch {
        setTimeout(poll, 3000); // backend briefly unreachable — keep trying quietly
      }
    };
    streamRun(runId, (ev, data) => {
      if (ev === "step") {
        setRuns((r) => {
          const cur = r[runId] ?? { steps: [], live: true };
          const steps = [...cur.steps.filter((s) => s.id !== data.id), data].sort((a, b) => a.seq - b.seq);
          return { ...r, [runId]: { ...cur, steps } };
        });
      } else if (ev === "run") {
        finished = true;
        setRuns((r) => ({ ...r, [runId]: { ...(r[runId] ?? { steps: [] }), run: data, live: false } }));
        setPending([]);
        qc.invalidateQueries({ queryKey: ["messages"] });
        qc.invalidateQueries({ queryKey: ["conversations"] });
        ["nav-counts", "dashboard", "controls", "findings", "evidence", "remediation", "approvals", "memory"].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
      }
    }).then(() => { if (!finished) poll(); }, () => poll());
  }, [qc]);

  const ask = React.useCallback(async (text: string, intent?: Record<string, string>) => {
    const t = text.trim();
    if (!t) return;
    setPending([{ id: `p${Date.now()}`, role: "user", content: t, cards: [], run_id: null, at: new Date().toISOString() }]);
    setInput("");
    try {
      const run = await api.post<AgentRun>("/api/agent/chat", { message: t, conversation_id: convId, intent });
      if (run.conversation_id !== convId) setParams({ c: String(run.conversation_id) }, { replace: !convId });
      attach(run.id);
    } catch (e) {
      setPending([]);
      toast.error((e as ApiError).message);
    }
  }, [convId, attach, setParams]);

  const ctx: CardCtx = { ask, attach };

  React.useEffect(() => {
    const q = params.get("q");
    const r = params.get("run");
    if (sentQ.current) return;
    if (q) { sentQ.current = true; ask(q); }
    else if (r) { sentQ.current = true; attach(Number(r)); }
  }, [params, ask, attach]);

  const persisted = msgs.data ?? [];
  const lastUser = [...persisted].reverse().find((m) => m.role === "user");
  const all: Msg[] = [...persisted, ...pending.filter((p) => p.content !== lastUser?.content)];
  const liveRun = Object.entries(runs).find(([, s]) => s.live);
  React.useEffect(() => { bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" }); }, [all.length, liveRun?.[1].steps.length]);

  // context panel focuses the live run or the latest assistant run
  const lastRunId = focusRun ?? [...all].reverse().find((m) => m.run_id)?.run_id ?? null;
  const ctxRun = useQuery({
    queryKey: ["run-context", lastRunId],
    enabled: !!lastRunId && !runs[lastRunId!],
    queryFn: async () => {
      const [run, st] = await Promise.all([api.get<AgentRun>(`/api/agent/runs/${lastRunId}`), api.get<{ steps: AgentStep[] }>(`/api/agent/runs/${lastRunId}/steps`)]);
      return { run, steps: st.steps, live: false } as RunState;
    },
  });
  const ctxState = lastRunId ? (runs[lastRunId] ?? ctxRun.data) : undefined;

  return (
    <div className="grid grid-cols-1 gap-5 lg:grid-cols-[minmax(0,1fr)_300px] xl:grid-cols-[minmax(0,1fr)_330px] 2xl:grid-cols-[250px_minmax(0,1fr)_340px]">
      {/* conversation history */}
      <aside className={cn("2xl:block lg:col-span-2 2xl:col-span-1", showHistory ? "block" : "hidden")}>
        <Button variant="primary" className="w-full" onClick={() => { setParams({}); setPending([]); setFocusRun(null); }}><MessageSquarePlus className="h-4 w-4" />New conversation</Button>
        <div className="mt-4 text-[11px] font-semibold uppercase tracking-wider text-subtle">History</div>
        <nav className="mt-2 max-h-[70vh] space-y-0.5 overflow-y-auto scrollbar-thin" aria-label="Conversations">
          {convs.data?.map((c) => (
            <button key={c.id} onClick={() => { setParams({ c: String(c.id) }); setPending([]); setFocusRun(null); setShowHistory(false); }}
              className={cn("w-full rounded-lg px-2.5 py-2 text-left transition-colors cursor-pointer", c.id === convId ? "bg-primary-soft dark:bg-surface-2" : "hover:bg-surface-2")}>
              <div className="truncate text-[13px] font-medium">{c.title}</div>
              <div className="text-[11px] text-muted">{relDays(c.updated_at)} · {c.messages} messages</div>
            </button>
          ))}
        </nav>
      </aside>

      {/* conversation */}
      <section className="flex min-h-[calc(100vh-8rem)] min-w-0 flex-col">
        <div className="mb-4 flex items-center justify-between gap-3">
          <div>
            <h1 className="flex items-center gap-2 text-[20px] font-semibold tracking-tight"><Brain className="h-5 w-5 text-accent" />AI Compliance Agent</h1>
            <p className="text-[12.5px] text-muted">Understand → Detect → Investigate → Act → Verify → Remember. Every tool call is authorised, risk-checked and audit-logged.</p>
          </div>
          <Button size="sm" variant="secondary" className="2xl:hidden" onClick={() => setShowHistory((v) => !v)}>{showHistory ? "Hide history" : "History"}</Button>
        </div>

        <div className="flex-1 space-y-4">
          {!all.length && (
            <Card className="p-6">
              <div className="text-[15px] font-semibold">Good {new Date().getHours() < 12 ? "morning" : "afternoon"}, {user?.name.split(" ")[0]}.</div>
              <p className="mt-1 text-[13px] text-muted">Give the agent an objective. It plans, retrieves permission-filtered data, detects gaps, investigates history, proposes remediation and asks you before any risky action.</p>
              <div className="mt-4 grid gap-2 sm:grid-cols-2">
                {STARTERS.map((s) => (
                  <button key={s.label} onClick={() => ask(s.label)} className="rounded-lg border border-border px-3.5 py-3 text-left text-[13px] transition-colors hover:border-accent/50 hover:bg-accent-soft/40 cursor-pointer">
                    <span className="mr-2 text-accent">{s.icon}</span>{s.label}
                  </button>
                ))}
              </div>
            </Card>
          )}
          {all.map((m) => m.role === "user" ? (
            <div key={m.id} className="flex justify-end nt-in">
              <div className="max-w-[85%] rounded-2xl rounded-br-md bg-primary px-4 py-2.5 text-[13.5px] text-primary-foreground">{m.content}</div>
            </div>
          ) : (
            <AssistantMessage key={m.id} m={m} runs={runs} ctx={ctx} onFocus={() => m.run_id && setFocusRun(m.run_id)} />
          ))}
          {liveRun && <ActivityPanel steps={liveRun[1].steps} live />}
          <div ref={bottom} />
        </div>

        <form className="sticky bottom-0 mt-4 bg-background pb-2 pt-2" onSubmit={(e) => { e.preventDefault(); ask(input); }}>
          <div className="flex items-end gap-2 rounded-xl border border-border-strong bg-surface p-2 shadow-card focus-within:ring-2 focus-within:ring-ring/30">
            <Textarea value={input} onChange={(e) => setInput(e.target.value)} rows={1} aria-label="Message the Compliance Agent"
              placeholder="Ask about controls, evidence, findings, audits… e.g. “Which findings are recurring?”"
              className="max-h-40 min-h-[40px] resize-none border-0 bg-transparent focus:ring-0"
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); ask(input); } }} />
            <Button type="submit" variant="primary" size="icon" disabled={!input.trim() || !!liveRun} aria-label="Send"><ArrowUp className="h-4 w-4" /></Button>
          </div>
          <p className="mt-1.5 text-center text-[11px] text-subtle">Answers use NovaTech demo data you are permitted to see. Potential gaps require human review — not legal advice.</p>
        </form>
      </section>

      {/* agent context */}
      <aside className="hidden lg:block">
        <div className="sticky top-20 space-y-3">
          <div className="text-[11px] font-semibold uppercase tracking-wider text-subtle">Agent context</div>
          <ContextPanel state={ctxState} />
        </div>
      </aside>
    </div>
  );
}

function AssistantMessage({ m, runs, ctx, onFocus }: { m: Msg; runs: Record<number, RunState>; ctx: CardCtx; onFocus: () => void }) {
  const cached = m.run_id ? runs[m.run_id] : undefined;
  const [showSteps, setShowSteps] = React.useState(!!cached); // runs from this session stay expanded
  const steps = useQuery({
    queryKey: ["steps", m.run_id], enabled: showSteps && !!m.run_id && !cached,
    queryFn: () => api.get<{ steps: AgentStep[] }>(`/api/agent/runs/${m.run_id}/steps`),
  });
  const list = cached?.steps ?? steps.data?.steps;
  return (
    <div className="space-y-3 nt-in" onMouseEnter={onFocus}>
      <div className="flex gap-3">
        <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-accent-soft text-accent"><Bot className="h-4 w-4" /></div>
        <div className="min-w-0 flex-1">
          <div className="mb-1 flex items-center gap-2 text-[11.5px] text-muted">
            <span className="font-semibold text-foreground">Compliance Agent</span><span>{fmtDateTime(m.at)}</span>
            {m.run_id && <button onClick={() => setShowSteps((v) => !v)} className="inline-flex items-center gap-1 text-accent hover:underline cursor-pointer"><Wrench className="h-3 w-3" />{showSteps ? "Hide" : "Show"} agent activity</button>}
          </div>
          <div className="whitespace-pre-line text-[13.5px] leading-relaxed text-foreground">{m.content}</div>
        </div>
      </div>
      {showSteps && list && <div className="pl-10"><ActivityPanel steps={list} live={false} /></div>}
      {!!m.cards?.length && <div className="space-y-3 pl-10">{m.cards.map((c, i) => <CardView key={i} card={c} ctx={ctx} />)}</div>}
    </div>
  );
}

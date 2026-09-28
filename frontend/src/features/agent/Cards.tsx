import * as React from "react";
import { Link, useNavigate } from "react-router";
import { AlertTriangle, ArrowRight, Brain, CheckCircle2, ChevronRight, CircleAlert, Clock, FileText, History, Repeat, ShieldCheck, Sparkles, XCircle } from "lucide-react";
import { toast } from "sonner";
import { KV, RiskBadge, SourceCitation, StatusBadge, WhyButton } from "@/components/app";
import { BriefView, ControlSimResult, DriftList, PolicySimResult } from "@/components/app/lab";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { api, ApiError } from "@/lib/api";
import { cn, fmtDate, title } from "@/lib/utils";
import type { Card as CardT, NextAction } from "@/types";

export type CardCtx = { ask: (prompt: string, intent?: Record<string, string>) => void; attach: (runId: number) => void };

function Shell({ icon, heading, tone = "neutral", children, right }: { icon?: React.ReactNode; heading: React.ReactNode; tone?: "neutral" | "danger" | "success" | "warning" | "ai"; children: React.ReactNode; right?: React.ReactNode }) {
  const bar = { neutral: "border-l-border-strong", danger: "border-l-danger", success: "border-l-success", warning: "border-l-warning", ai: "border-l-accent" }[tone];
  return (
    <div className={cn("nt-in rounded-card border border-border border-l-[3px] bg-surface shadow-card", bar)}>
      <div className="flex items-center justify-between gap-2 px-4 pt-3 pb-2">
        <div className="flex items-center gap-2 text-[11.5px] font-semibold uppercase tracking-wider text-muted">{icon}{heading}</div>
        {right}
      </div>
      <div className="px-4 pb-4">{children}</div>
    </div>
  );
}

function Actions({ actions, ctx }: { actions: NextAction[]; ctx: CardCtx }) {
  const nav = useNavigate();
  return (
    <div className="flex flex-wrap gap-2">
      {actions.map((a, i) => (
        <Button key={i} size="sm" variant={i === 0 ? "primary" : "secondary"} onClick={async () => {
          if (a.kind === "navigate" && a.to) nav(a.to);
          else if (a.kind === "agent" && a.prompt) ctx.ask(a.prompt, a.intent);
          else if (a.kind === "api" && a.path) {
            try { const r: any = await api.post(a.path); toast.message(r?.result ? `Verification ${r.result}` : "Done"); } catch (e) { toast.error((e as ApiError).message); }
          }
        }}>
          {a.kind === "agent" && <Sparkles className="h-3.5 w-3.5" />}{a.label}{a.kind === "navigate" && <ArrowRight className="h-3.5 w-3.5" />}
        </Button>
      ))}
    </div>
  );
}

function ApprovalCard({ a, planCode, ctx }: { a: any; planCode?: string; ctx: CardCtx }) {
  const [state, setState] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState<string | null>(null);
  const decide = async (d: "approve" | "reject" | "request-changes") => {
    setBusy(d);
    try {
      const r = await api.post<any>(`/api/approvals/${a.id}/${d}`, { note: d === "approve" ? "Approved in agent workspace" : "" });
      setState(r.approval.status);
      if (r.run) { toast.success(`${a.code} approved — executing and verifying`); ctx.attach(r.run.id); }
      else if (r.message) toast.message(r.message);
      else toast.message(`${a.code} ${title(r.approval.status).toLowerCase()}`);
    } catch (e) {
      const err = e as ApiError;
      toast.error(err.status === 403 ? `Denied: requires ${err.why?.required_permission}` : err.message);
    } finally { setBusy(null); }
  };
  const tone = a.risk_level === "CRITICAL" || a.risk_level === "HIGH" ? "danger" : "warning";
  return (
    <Shell tone={tone} icon={<CircleAlert className="h-3.5 w-3.5 text-danger" />} heading={`${a.risk_level}-risk action · human approval required`} right={<Badge tone="neutral">{a.code}</Badge>}>
      <div className="text-[15px] font-semibold">AI wants to: {a.title}</div>
      <KV className="mt-3" items={[
        ["Reason", a.reason],
        ["Affected", Object.entries(a.affected ?? {}).map(([k, v]) => `${v} ${k}`).join(" · ")],
        ["Evidence", a.evidence_refs?.length ? a.evidence_refs.join(", ") : "—"],
        ["Risk", <RiskBadge risk={a.risk_level} />],
        ["Required approver", <span className="font-mono text-[12px]">{a.required_permission}</span>],
        ["Plan", planCode ?? "—"],
      ]} />
      <p className="mt-3 text-[12px] text-muted">Execution is blocked in backend code until a permitted human decides. Actions run through the IAM Demo Connector (simulated — no real accounts are changed).</p>
      {state ? (
        <div className="mt-3"><StatusBadge status={state} /></div>
      ) : (
        <div className="mt-3 flex flex-wrap gap-2">
          <Button size="sm" variant="success" loading={busy === "approve"} onClick={() => decide("approve")}><CheckCircle2 className="h-3.5 w-3.5" />Approve</Button>
          <Button size="sm" variant="secondary" loading={busy === "reject"} onClick={() => decide("reject")}><XCircle className="h-3.5 w-3.5" />Reject</Button>
          <Button size="sm" variant="ghost" loading={busy === "request-changes"} onClick={() => decide("request-changes")}>Request Changes</Button>
          {a.evidence_refs?.length ? <Link to="/evidence" className="ml-auto self-center text-[12.5px] text-accent hover:underline">Review Evidence</Link> : null}
        </div>
      )}
    </Shell>
  );
}

export function CardView({ card, ctx }: { card: CardT; ctx: CardCtx }) {
  switch (card.type) {
    case "summary_metrics":
      return (
        <Shell tone="ai" icon={<Sparkles className="h-3.5 w-3.5 text-accent" />} heading={card.title}>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
            {card.items.map((m: any) => (
              <div key={m.label} className="rounded-lg bg-surface-2 px-3 py-2.5">
                <div className="text-[11.5px] text-muted">{m.label}</div>
                <div className={cn("text-[22px] font-semibold tabular", m.tone === "danger" ? "text-danger" : m.tone === "warning" ? "text-warning" : "text-foreground")}>{m.value}</div>
              </div>
            ))}
          </div>
          <p className="mt-2 text-[11.5px] text-subtle">NovaTech Compliance Readiness Indicators — prototype indicators, not certification scores.</p>
        </Shell>
      );
    case "gap_list":
      return (
        <Shell tone="warning" icon={<AlertTriangle className="h-3.5 w-3.5 text-warning" />} heading={`${card.title} · ${card.subjects.length}`}>
          <ul className="divide-y divide-border">
            {card.subjects.map((s: any) => (
              <li key={s.subject_code} className="flex flex-wrap items-center gap-2 py-2 text-[13px]">
                <span className="font-mono text-[12px] text-muted w-[72px]">{s.subject_code}</span>
                <span className="min-w-0 flex-1 font-medium">{s.subject_name}</span>
                <div className="flex flex-wrap gap-1">{s.gap_types.slice(0, 3).map((g: string) => <Badge key={g} tone="neutral" className="normal-case tracking-normal font-medium">{title(g)}</Badge>)}{s.gap_types.length > 3 && <Badge tone="neutral">+{s.gap_types.length - 3}</Badge>}</div>
                <RiskBadge risk={s.severity} />
              </li>
            ))}
          </ul>
        </Shell>
      );
    case "control_risk":
      return (
        <Shell tone="danger" icon={<ShieldCheck className="h-3.5 w-3.5 text-danger" />} heading="Control at risk" right={<WhyButton kind="control" code={card.control.code} />}>
          <div className="text-[15px] font-semibold">{card.control.code} — {card.control.name}</div>
          <KV className="mt-3" items={[
            ["Risk", <RiskBadge risk={card.risk} score={card.score} />], ["Status", <StatusBadge status={card.status} />],
            ["Reason", card.reason],
            ["Historical finding", card.previous_findings?.length ? card.previous_findings.join(", ") : "None"],
            ["Recurring", card.recurring ? <Badge tone="danger">Recurring</Badge> : "No"],
            ["Evidence", <span>{card.evidence.map((e: any) => e.name).join(", ") || "None"} · <StatusBadge status={card.evidence_state} /></span>],
            ["Recommended action", card.recommended],
          ]} />
          <div className="mt-3 flex flex-wrap gap-2">
            <Link to={`/controls/${card.control.id}`}><Button size="sm" variant="secondary">View control</Button></Link>
            {card.finding && <Link to={`/findings/${card.finding.id}`}><Button size="sm" variant="secondary">View Finding</Button></Link>}
            <Button size="sm" variant="secondary" onClick={() => ctx.ask(`Investigate ${card.control.code}`, { intent: "investigate_control", control_code: card.control.code })}>Investigate</Button>
            {card.finding && <Button size="sm" variant="primary" onClick={() => ctx.ask(`Create a remediation plan for ${card.finding.code}`, { intent: "remediation_plan", finding_code: card.finding.code })}>Create Remediation</Button>}
          </div>
        </Shell>
      );
    case "recurring":
      return (
        <Shell tone="danger" icon={<Repeat className="h-3.5 w-3.5 text-danger" />} heading={`Recurring findings · ${card.items.length}`}>
          {!card.items.length && <p className="text-[13px] text-muted">No recurring findings are active.</p>}
          <div className="space-y-3">
            {card.items.map((r: any) => (
              <div key={r.control_code + r.category} className="rounded-lg border border-border p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-[12px] text-muted">{r.control_code}</span>
                  <span className="text-[13.5px] font-semibold">{r.control_name}</span>
                  <Badge tone="danger">Recurring</Badge>
                  <span className="ml-auto text-[12px] text-muted">Remediation effectiveness: <b className={r.effectiveness.level === "LOW" ? "text-danger" : "text-warning"}>{r.effectiveness.level}</b></span>
                </div>
                <div className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-[12.5px] sm:grid-cols-4">
                  <div><div className="text-muted">First detected</div><div className="font-medium">{fmtDate(r.first_detected)}</div></div>
                  <div><div className="text-muted">Occurrences</div><div className="font-medium tabular">{r.occurrences}</div></div>
                  <div><div className="text-muted">Previous remediation</div><div className="font-medium">{r.previous_remediation}</div></div>
                  <div><div className="text-muted">Verification</div><div className="font-medium">{r.verification_summary}</div></div>
                </div>
                <div className="mt-2 flex items-center gap-1 overflow-x-auto text-[11.5px] scrollbar-thin">
                  {r.timeline.map((o: any, i: number) => (
                    <React.Fragment key={o.finding_code}>
                      {i > 0 && <ChevronRight className="h-3 w-3 shrink-0 text-subtle" />}
                      <Link to={`/findings/${o.finding_id}`} className="shrink-0 rounded-md bg-surface-2 px-2 py-1 hover:bg-accent-soft">
                        <span className="font-mono">{o.finding_code}</span> · {fmtDate(o.detected_at, { month: "short", year: "numeric" })} · {title(o.status)}
                      </Link>
                    </React.Fragment>
                  ))}
                </div>
                <p className="mt-2 text-[12.5px]"><span className="font-semibold text-accent">AI analysis:</span> {r.interpretation} <span className="text-subtle">({r.interpretation_label})</span></p>
              </div>
            ))}
          </div>
        </Shell>
      );
    case "top_risks":
      return (
        <Shell icon={<AlertTriangle className="h-3.5 w-3.5" />} heading="Top risks before audit · deterministic risk model">
          <ol className="space-y-1.5">
            {card.items.map((t: any, i: number) => (
              <li key={t.code} className="flex items-center gap-3 text-[13px]">
                <span className="w-4 text-right text-muted tabular">{i + 1}</span>
                <Link to={`/controls/${t.id}`} className="min-w-0 flex-1 truncate hover:underline"><span className="font-mono text-[12px] text-muted">{t.code}</span> {t.name}</Link>
                <StatusBadge status={t.status} /><RiskBadge risk={t.category} score={t.score} />
              </li>
            ))}
          </ol>
        </Shell>
      );
    case "next_actions":
      return (
        <div className="nt-in rounded-card border border-accent/25 bg-accent-soft/50 px-4 py-3">
          <div className="mb-2 text-[11.5px] font-semibold uppercase tracking-wider text-accent">Next best action</div>
          <Actions actions={card.actions} ctx={ctx} />
        </div>
      );
    case "risk_explanation": {
      const r = card.risk;
      return (
        <Shell tone="danger" icon={<ShieldCheck className="h-3.5 w-3.5 text-danger" />} heading={`Why is ${card.control.code} ${r.category.toLowerCase()} risk?`} right={<RiskBadge risk={r.category} score={r.score} />}>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-5">
            {(["severity", "likelihood", "criticality", "freshness", "recurrence"] as const).map((k) => (
              <div key={k} className="rounded-lg bg-surface-2 px-3 py-2">
                <div className="text-[11px] uppercase tracking-wider text-muted">{k === "freshness" ? "Evidence freshness" : title(k)}</div>
                <div className="text-[17px] font-semibold tabular">{Number(r.factors[k]).toFixed(2)}</div>
              </div>
            ))}
          </div>
          <ul className="mt-3 space-y-1 text-[12.5px] text-foreground">{r.explanation.map((e: string, i: number) => <li key={i} className="flex gap-2"><span className="text-subtle">•</span>{e}</li>)}</ul>
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <div>
              <div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-subtle">Historical findings</div>
              {card.findings.slice(0, 4).map((f: any) => (
                <Link key={f.id} to={`/findings/${f.id}`} className="flex items-center justify-between py-1 text-[12.5px] hover:underline"><span><span className="font-mono text-muted">{f.code}</span> {fmtDate(f.detected_at)}</span><StatusBadge status={f.status} /></Link>
              ))}
            </div>
            <div>
              <div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-subtle">Evidence freshness</div>
              {card.evidence.map((e: any) => (
                <Link key={e.id} to={`/evidence?focus=${e.id}`} className="flex items-center justify-between py-1 text-[12.5px] hover:underline"><span><span className="font-mono text-muted">{e.code}</span> {e.name}</span><StatusBadge status={e.status} /></Link>
              ))}
            </div>
          </div>
          <p className="mt-3 text-[11.5px] text-subtle">{r.label} · score calculated by backend rules; AI explanation cannot change it.</p>
        </Shell>
      );
    }
    case "citations":
      return (
        <Shell icon={<FileText className="h-3.5 w-3.5" />} heading={`Sources · ${card.results.length} permitted passages`}>
          {card.results.length ? <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">{card.results.map((c: any) => <SourceCitation key={c.chunk_id} c={c} />)}</div>
            : <p className="text-[13px] text-muted">Insufficient evidence in documents you are permitted to access.</p>}
        </Shell>
      );
    case "investigation": {
      const r = card.recurring;
      return (
        <Shell tone={r ? "danger" : "success"} icon={<History className="h-3.5 w-3.5" />} heading={`Investigation · ${card.control.code}`} right={r ? <Badge tone="danger">{card.verdict}</Badge> : <Badge tone="success">{card.verdict}</Badge>}>
          {r && (
            <>
              <ol className="relative space-y-2.5 border-l border-border pl-4">
                {r.timeline.map((o: any) => (
                  <li key={o.finding_code} className="relative text-[12.5px]">
                    <span className={cn("absolute -left-[21px] top-1 h-2.5 w-2.5 rounded-full ring-2 ring-surface", o.status === "CLOSED" ? "bg-success" : "bg-danger")} />
                    <div className="font-medium">{fmtDate(o.detected_at)} · {o.audit?.name ?? "Continuous monitoring"} — <span className="font-mono">{o.finding_code}</span></div>
                    <div className="text-muted">{o.remediation.map((p: any) => `${p.code}: ${p.summary || p.title}`).join("; ") || "No remediation yet"}</div>
                    <div className="mt-0.5 flex flex-wrap gap-1">{o.verification.map((v: any) => <StatusBadge key={v.code} status={v.result} />)}<StatusBadge status={o.status} /></div>
                  </li>
                ))}
              </ol>
              <div className="mt-3 rounded-lg bg-surface-2 p-3">
                <div className="text-[11.5px] font-semibold uppercase tracking-wider text-muted">Potential root causes <span className="normal-case font-normal tracking-normal text-subtle">— {r.hypotheses_label}</span></div>
                <ul className="mt-1.5 space-y-1.5 text-[12.5px]">{r.hypotheses.map((h: any) => <li key={h.factor}><b>{h.factor}.</b> <span className="text-muted">{h.basis}</span></li>)}</ul>
              </div>
            </>
          )}
          {!!card.memory?.length && (
            <div className="mt-3">
              <div className="mb-1 flex items-center gap-1.5 text-[11.5px] font-semibold uppercase tracking-wider text-muted"><Brain className="h-3.5 w-3.5" />Recalled from audit memory</div>
              <ul className="space-y-1 text-[12.5px]">{card.memory.slice(0, 5).map((m: any) => <li key={m.id} className="flex items-start gap-2"><Badge tone="neutral" className="shrink-0">{m.category}</Badge><span className="text-muted">{m.summary}</span></li>)}</ul>
            </div>
          )}
        </Shell>
      );
    }
    case "remediation_plan":
      return (
        <Shell tone="ai" icon={<ShieldCheck className="h-3.5 w-3.5 text-accent" />} heading={`Remediation plan · ${card.plan.code}`} right={<StatusBadge status={card.plan.status} />}>
          <div className="text-[14px] font-semibold">{card.plan.title}</div>
          <p className="text-[12.5px] text-muted">{card.plan.rationale}</p>
          <div className="mt-3 overflow-x-auto scrollbar-thin">
            <table className="w-full text-[12.5px]">
              <thead className="text-[11px] uppercase tracking-wider text-muted"><tr><th className="py-1.5 text-left">#</th><th className="text-left">Task</th><th className="text-left hidden sm:table-cell">Owner</th><th className="text-left">Due</th><th className="text-left">Risk</th><th className="text-left">Status</th></tr></thead>
              <tbody className="divide-y divide-border">
                {card.tasks.map((t: any) => (
                  <tr key={t.id}><td className="py-1.5 pr-2 text-muted tabular">{t.seq}</td><td className="pr-2">{t.title}<div className="text-[11px] text-subtle">Evidence: {t.evidence_required}{t.depends_on ? ` · after #${t.depends_on}` : ""}</div></td>
                    <td className="hidden sm:table-cell pr-2 text-muted">{t.owner}</td><td className="pr-2 text-muted whitespace-nowrap">{fmtDate(t.due_date, { day: "2-digit", month: "short" })}</td>
                    <td className="pr-2"><RiskBadge risk={t.risk} /></td><td><StatusBadge status={t.status} /></td></tr>
                ))}
              </tbody>
            </table>
          </div>
        </Shell>
      );
    case "approval":
      return <ApprovalCard a={card.approval} planCode={card.plan_code} ctx={ctx} />;
    case "verification": {
      const ok = card.result === "PASSED";
      return (
        <Shell tone={ok ? "success" : "danger"} icon={ok ? <CheckCircle2 className="h-3.5 w-3.5 text-success" /> : <XCircle className="h-3.5 w-3.5 text-danger" />} heading={`Post-action verification · ${card.result}`}>
          {card.before != null && (
            <div className="flex items-center gap-4">
              <div className="rounded-lg bg-danger-soft px-4 py-2 text-center"><div className="text-[11px] uppercase tracking-wider text-danger">Before</div><div className="text-[24px] font-semibold tabular text-danger">{card.before}</div><div className="text-[11px] text-danger">inactive accounts</div></div>
              <ArrowRight className="h-5 w-5 text-subtle" />
              <div className={cn("rounded-lg px-4 py-2 text-center", ok ? "bg-success-soft" : "bg-surface-2")}><div className="text-[11px] uppercase tracking-wider text-success">After</div><div className="text-[24px] font-semibold tabular text-success">{card.after ?? "?"}</div><div className="text-[11px] text-success">inactive accounts</div></div>
            </div>
          )}
          {card.message && <p className="mt-2 text-[13px] text-danger">{card.message}</p>}
          <ul className="mt-3 space-y-1 text-[12.5px]">
            {card.checks.map((c: any) => <li key={c.name} className="flex items-center gap-2">{c.passed ? <CheckCircle2 className="h-3.5 w-3.5 text-success" /> : <XCircle className="h-3.5 w-3.5 text-danger" />}{c.name}: expected <b>{String(c.expected)}</b>, actual <b>{String(c.actual)}</b></li>)}
          </ul>
          {card.transition && (
            <div className="mt-3 flex flex-wrap items-center gap-1.5 text-[12px]">
              <span className="text-muted">{card.control.code}:</span>
              {card.transition.map((s: string, i: number) => (
                <React.Fragment key={s}>{i > 0 && <ChevronRight className="h-3.5 w-3.5 text-subtle" />}<Badge tone={s === "PASS" ? "success" : s === "HIGH RISK" ? "danger" : "accent"}>{s}</Badge></React.Fragment>
              ))}
            </div>
          )}
          <KV className="mt-3" items={[
            ["New evidence", card.evidence ? `${card.evidence.code} — ${card.evidence.name}` : "—"],
            ["Control test", card.control_test ? `${card.control_test.code} · ${card.control_test.result}` : "—"],
            ["Finding", <Link to={`/findings/${card.finding.id}`} className="hover:underline">{card.finding.code} · {title(card.finding.status)}</Link>],
          ]} />
        </Shell>
      );
    }
    case "memory_update":
      return (
        <Shell tone="ai" icon={<Brain className="h-3.5 w-3.5 text-accent" />} heading="Audit Memory Updated">
          <ul className="space-y-1.5 text-[12.5px]">{card.records.map((m: any) => <li key={m.id} className="flex items-start gap-2"><Badge tone="accent" className="shrink-0">{m.category}</Badge><span>{m.summary}</span></li>)}</ul>
          <Link to="/memory" className="mt-2 inline-block text-[12.5px] text-accent hover:underline">Open Agent Memory →</Link>
        </Shell>
      );
    case "memory":
      return (
        <Shell tone="ai" icon={<Brain className="h-3.5 w-3.5 text-accent" />} heading={`Audit memory · ${card.records.length} records`}>
          <ul className="space-y-2 text-[12.5px]">
            {card.records.slice(0, 8).map((m: any) => (
              <li key={m.id} className="rounded-lg bg-surface-2 px-3 py-2">
                <div className="flex flex-wrap items-center gap-2"><Badge tone="neutral">{m.category}</Badge><span className="text-muted">{fmtDate(m.occurred_at)} · {m.source_label}</span>{m.verification && <StatusBadge status={m.verification} />}</div>
                <div className="mt-1">{m.summary}</div>
                {m.current_relevance && <div className="mt-1 text-accent">Current relevance: {m.current_relevance}</div>}
              </li>
            ))}
          </ul>
        </Shell>
      );
    case "changes": {
      const order = ["NEW", "CHANGED", "RESOLVED", "RECURRING", "AT_RISK"];
      return (
        <Shell icon={<Clock className="h-3.5 w-3.5" />} heading={`What changed since ${card.baseline?.name ?? "the last audit"}`}>
          <div className="mb-3 flex flex-wrap gap-2">{order.map((k) => <div key={k} className="rounded-lg bg-surface-2 px-3 py-1.5 text-[12px]"><StatusBadge status={k} /> <b className="ml-1 tabular">{card.counts?.[k] ?? 0}</b></div>)}</div>
          <ul className="divide-y divide-border">
            {[...card.items].sort((a: any, b: any) => order.indexOf(a.kind) - order.indexOf(b.kind)).slice(0, 18).map((it: any, i: number) => (
              <li key={i} className="flex flex-wrap items-center gap-2 py-1.5 text-[12.5px]"><StatusBadge status={it.kind} /><span className="text-muted w-[88px]">{it.area}</span><span className="font-mono text-[11.5px] text-muted">{it.code}</span><span className="flex-1 min-w-0">{it.title}</span><span className="text-muted">{it.detail}</span></li>
            ))}
          </ul>
        </Shell>
      );
    }
    case "table": {
      const link = (r: any) => card.link_kind === "controls" ? `/controls/${r.id}` : card.link_kind === "findings" ? `/findings/${r.id}` : card.link_kind === "evidence" ? `/evidence?focus=${r.id}` : null;
      return (
        <Shell icon={<ChevronRight className="h-3.5 w-3.5" />} heading={`${card.title} · ${card.rows.length}`}>
          {card.rows.length ? (
            <div className="overflow-x-auto scrollbar-thin">
              <table className="w-full text-[12.5px]">
                <thead className="text-[11px] uppercase tracking-wider text-muted"><tr>{card.columns.map((c: string) => <th key={c} className="py-1.5 pr-3 text-left whitespace-nowrap">{title(c)}</th>)}</tr></thead>
                <tbody className="divide-y divide-border">
                  {card.rows.map((r: any, i: number) => (
                    <tr key={i}>{card.columns.map((c: string, j: number) => {
                      const v = r[c];
                      const content = ["status", "risk_category", "severity"].includes(c) ? (c === "status" ? <StatusBadge status={v} /> : <RiskBadge risk={v} />)
                        : /date|valid_until|last_tested/.test(c) ? fmtDate(v) : v ?? "—";
                      const l = link(r);
                      return <td key={c} className="py-1.5 pr-3">{j === 0 && l ? <Link to={l} className="font-mono text-accent hover:underline">{content}</Link> : content}</td>;
                    })}</tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <p className="text-[13px] text-muted">You're all clear.</p>}
        </Shell>
      );
    }
    case "report":
      return (
        <Shell tone="success" icon={<FileText className="h-3.5 w-3.5 text-success" />} heading="Report ready">
          <div className="text-[14px] font-semibold">{card.title}</div>
          <div className="mt-3 flex gap-2"><Link to={`/reports/${card.report_id}`}><Button size="sm" variant="primary">Open report</Button></Link></div>
        </Shell>
      );
    case "simulation":
      return <Shell tone="ai" icon={<Sparkles className="h-3.5 w-3.5 text-accent" />} heading={`Compliance Simulator · ${card.control.code}`}><ControlSimResult r={card} /></Shell>;
    case "policy_simulation":
      return <Shell tone="ai" icon={<Sparkles className="h-3.5 w-3.5 text-accent" />} heading={`Policy Lab · ${card.policy.code} → ${card.proposed_interval_days} days`}><PolicySimResult r={card} /></Shell>;
    case "brief":
      return <BriefView b={card} compact />;
    case "drift":
      return <Shell tone="warning" icon={<AlertTriangle className="h-3.5 w-3.5 text-warning" />} heading={`Potential control drift · ${card.items.length}`}><DriftList items={card.items} /></Shell>;
    case "notice":
      return <div className="rounded-lg bg-warning-soft px-3 py-2 text-[12.5px] text-warning">{card.text}</div>;
    default:
      return null;
  }
}

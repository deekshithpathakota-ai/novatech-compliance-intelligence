import * as React from "react";
import { Link, useNavigate, useParams } from "react-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Send, Sparkles } from "lucide-react";
import { toast } from "sonner";
import { KV, PageHeader, QueryView, RiskBadge, StatusBadge, Timeline, WhyButton } from "@/components/app";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Textarea } from "@/components/ui/input";
import { Progress } from "@/components/ui/misc";
import { useAuth } from "@/hooks/useAuth";
import { api, ApiError } from "@/lib/api";
import { fmtDate, fmtDateTime, title } from "@/lib/utils";

export default function FindingDetail() {
  const { id } = useParams();
  const nav = useNavigate();
  const qc = useQueryClient();
  const { can } = useAuth();
  const q = useQuery({ queryKey: ["findings", "detail", id], queryFn: () => api.get<any>(`/api/findings/${id}`) });
  const [comment, setComment] = React.useState("");
  const act = async (fn: () => Promise<any>, ok: string) => {
    try { await fn(); toast.success(ok); ["findings", "nav-counts", "dashboard", "controls"].forEach((k) => qc.invalidateQueries({ queryKey: [k] })); }
    catch (e) { toast.error((e as ApiError).message); }
  };
  return (
    <QueryView q={q}>
      {(f) => (
        <>
          <PageHeader
            eyebrow={<Link to="/findings" className="hover:underline">Findings</Link>}
            title={<span className="flex flex-wrap items-center gap-3"><span className="font-mono text-muted">{f.code}</span>{f.title}</span>}
            description={f.description}
            actions={<>
              {f.recurring && <Badge tone="danger">Recurring · {f.prior_occurrences + 1}×</Badge>}
              <WhyButton kind="control" code={f.control.code} label="Why this risk?" />
              {["OPEN", "IN_REMEDIATION"].includes(f.status) && can("REMEDIATION_CREATE") && (
                <Button variant="primary" onClick={() => nav(`/agent?q=${encodeURIComponent(`Create a remediation plan for ${f.code}`)}`)}><Sparkles className="h-3.5 w-3.5" />Create remediation</Button>
              )}
              {can("EVIDENCE_REQUEST") && f.status !== "CLOSED" && (
                <Button onClick={() => act(() => api.post(`/api/findings/${f.id}/request-evidence`, { reason: `Evidence needed to resolve ${f.code}: ${f.title}` }), "Evidence requested (Demo Notification)")}><Send className="h-3.5 w-3.5" />Request evidence</Button>
              )}
              {can("FINDINGS_MANAGE") && f.status === "READY_FOR_CLOSURE" && (
                <Button variant="success" disabled={!f.can_close} onClick={() => act(() => api.post(`/api/findings/${f.id}/close`), `${f.code} closed`)}><CheckCircle2 className="h-3.5 w-3.5" />Close finding</Button>
              )}
            </>}
          />
          <div className="grid grid-cols-1 gap-5 lg:grid-cols-[minmax(0,1fr)_360px]">
            <div className="space-y-5">
              <Card><CardHeader title="Finding" /><CardBody>
                <KV items={[
                  ["Severity", <RiskBadge risk={f.severity} />], ["Status", <StatusBadge status={f.status} />],
                  ["Current risk", <RiskBadge risk={f.risk.category} score={f.risk.score} />],
                  ["Control", <Link to={`/controls/${f.control.id}`} className="text-accent hover:underline">{f.control.code} — {f.control.name}</Link>],
                  ["Requirement", f.requirement ? `${f.requirement.code} — ${f.requirement.title}` : "—"],
                  ["Source", f.audit ? <Link to={`/audits/${f.audit.id}`} className="hover:underline">{f.audit.name}</Link> : title(f.source)],
                  ["Owner", f.owner ?? "—"], ["Detected", fmtDate(f.detected_at)], ["Due", fmtDate(f.due_date)],
                  ["Root cause", f.root_cause || "Under investigation"],
                  ["Evidence", f.evidence.length ? f.evidence.map((e: any) => `${e.code} (${e.status.toLowerCase()})`).join(", ") : "None current"],
                ]} />
              </CardBody></Card>

              {f.recurrence && (
                <Card className="border-l-[3px] border-l-danger"><CardHeader title="AI analysis · recurrence" description={f.recurrence.interpretation_label} /><CardBody className="space-y-3 text-[13px]">
                  <p>{f.recurrence.interpretation}</p>
                  <KV items={[["First detected", fmtDate(f.recurrence.first_detected)], ["Occurrences", f.recurrence.occurrences], ["Previous remediation", f.recurrence.previous_remediation], ["Verification", f.recurrence.verification_summary], ["Remediation effectiveness", <Badge tone={f.recurrence.effectiveness.level === "LOW" ? "danger" : "warning"}>{f.recurrence.effectiveness.level}</Badge>]]} />
                  <div><div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-subtle">Potential root causes — {f.recurrence.hypotheses_label}</div>
                    <ul className="space-y-1.5">{f.recurrence.hypotheses.map((h: any) => <li key={h.factor}><b>{h.factor}.</b> <span className="text-muted">{h.basis}</span></li>)}</ul></div>
                </CardBody></Card>
              )}

              <Card><CardHeader title="Remediation" description={f.plans.length ? `${f.plans.length} plan(s)` : "No remediation plan yet"} /><CardBody className="space-y-4">
                {f.plans.map((pl: any) => (
                  <div key={pl.id} className="rounded-lg border border-border p-3">
                    <div className="flex flex-wrap items-center justify-between gap-2"><div className="text-[13.5px] font-semibold"><span className="font-mono text-muted">{pl.code}</span> {pl.title}</div><StatusBadge status={pl.status} /></div>
                    <Progress value={pl.progress} tone={pl.status === "COMPLETED" ? "success" : "accent"} className="mt-2" />
                    <ul className="mt-2 space-y-1 text-[12.5px]">{pl.tasks.map((t: any) => <li key={t.id} className="flex items-center gap-2"><span className="w-4 text-muted tabular">{t.seq}</span><span className="flex-1">{t.title}</span><RiskBadge risk={t.risk} /><StatusBadge status={t.overdue ? "OVERDUE" : t.status} /></li>)}</ul>
                  </div>
                ))}
                {f.approvals.map((a: any) => (
                  <div key={a.id} className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-warning-soft/60 px-3 py-2 text-[12.5px]">
                    <span><b>{a.code}</b> {a.title} · requires <span className="font-mono">{a.required_permission}</span></span><StatusBadge status={a.status} />
                  </div>
                ))}
                {!f.plans.length && <p className="text-[13px] text-muted">Use “Create remediation” to have the agent generate a multi-step plan with approvals.</p>}
              </CardBody></Card>

              <Card><CardHeader title="Verification" /><CardBody>
                {f.verifications.length ? f.verifications.map((v: any) => (
                  <div key={v.code} className="flex items-start justify-between gap-2 border-b border-border py-2 last:border-0 text-[12.5px]">
                    <div><b className="font-mono">{v.code}</b> · {fmtDate(v.at)}<div className="text-muted">{v.checks.map((c: any) => `${c.name}: ${c.actual}`).join(" · ")}</div></div><StatusBadge status={v.result} />
                  </div>
                )) : <p className="text-[13px] text-muted">Not yet verified. A finding can only be closed after verification passes.</p>}
              </CardBody></Card>

              <Card><CardHeader title="Historical findings on this control" /><CardBody>
                {f.historical_findings.length ? f.historical_findings.map((h: any) => (
                  <Link key={h.id} to={`/findings/${h.id}`} className="flex items-center justify-between gap-2 border-b border-border py-2 text-[12.5px] last:border-0 hover:underline">
                    <span><span className="font-mono text-muted">{h.code}</span> {fmtDate(h.detected_at)} · {h.audit?.name ?? "Continuous monitoring"}</span><StatusBadge status={h.status} />
                  </Link>
                )) : <p className="text-[13px] text-muted">No previous occurrence in audit memory.</p>}
              </CardBody></Card>
            </div>

            <div className="space-y-5">
              <Card><CardHeader title="Timeline" /><CardBody><Timeline items={f.history.map((h: any) => ({ title: `${title(h.event)}${h.note ? ` — ${h.note}` : ""}`, at: h.at, type: h.event.includes("passed") ? "verification_passed" : h.event.includes("failed") ? "verification_failed" : h.event === "created" ? "finding_created" : h.event === "closed" ? "finding_closed" : undefined, actor_type: h.actor_type }))} /></CardBody></Card>
              <Card><CardHeader title="Comments" /><CardBody className="space-y-3">
                {f.comments.map((c: any) => <div key={c.id} className="rounded-lg bg-surface-2 px-3 py-2 text-[12.5px]"><div className="font-medium">{c.user} <span className="font-normal text-muted">· {fmtDateTime(c.at)}</span></div>{c.body}</div>)}
                {can("FINDINGS_RESPOND") && (
                  <form onSubmit={(e) => { e.preventDefault(); if (!comment.trim()) return; act(() => api.post(`/api/findings/${f.id}/comments`, { body: comment }), "Comment added").then(() => setComment("")); }} className="space-y-2">
                    <Textarea rows={2} value={comment} onChange={(e) => setComment(e.target.value)} placeholder="Respond or request clarification…" aria-label="Comment" />
                    <Button size="sm" type="submit">Add comment</Button>
                  </form>
                )}
              </CardBody></Card>
              <Card><CardHeader title="Audit trail" /><CardBody className="space-y-1.5">
                {f.audit_trail.length ? f.audit_trail.map((a: any, i: number) => (
                  <div key={i} className="text-[12px]"><span className="text-muted">{fmtDateTime(a.at)}</span> · <b>{a.actor}</b> · {a.action} <StatusBadge status={a.authorization === "DENIED" ? "REJECTED" : undefined} /></div>
                )) : <p className="text-[12.5px] text-muted">No trail entries yet.</p>}
              </CardBody></Card>
            </div>
          </div>
        </>
      )}
    </QueryView>
  );
}

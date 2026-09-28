import * as React from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, ShieldAlert, XCircle } from "lucide-react";
import { toast } from "sonner";
import { EmptyState, KV, PageHeader, QueryView, RiskBadge, StatusBadge } from "@/components/app";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Progress } from "@/components/ui/misc";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useAuth } from "@/hooks/useAuth";
import { api, ApiError } from "@/lib/api";
import { cn, fmtDate, fmtDateTime } from "@/lib/utils";

function Approvals() {
  const q = useQuery({ queryKey: ["approvals"], queryFn: () => api.get<any[]>("/api/approvals") });
  const qc = useQueryClient();
  const nav = useNavigate();
  const [busy, setBusy] = React.useState<string | null>(null);
  const decide = async (a: any, d: string) => {
    setBusy(`${a.id}${d}`);
    try {
      const r = await api.post<any>(`/api/approvals/${a.id}/${d}`, { note: "" });
      ["approvals", "remediation", "nav-counts", "dashboard"].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
      if (r.run) {
        toast.success(`${a.code} approved — the agent is executing and verifying`, { action: { label: "Watch", onClick: () => nav(`/agent?c=${r.run.conversation_id}&run=${r.run.id}`) } });
        nav(`/agent?c=${r.run.conversation_id}&run=${r.run.id}`);
      } else toast.message(r.message ?? `${a.code} ${r.approval.status.toLowerCase().replace("_", " ")}`);
    } catch (e) {
      const err = e as ApiError;
      toast.error(err.status === 403 ? `Denied — requires ${err.why?.required_permission}. Your role: ${err.why?.your_role}.` : err.message);
    } finally { setBusy(null); }
  };
  return (
    <QueryView q={q} empty={<EmptyState title="No approvals" />}>
      {(rows) => {
        const pending = rows.filter((a) => a.status === "PENDING");
        const decided = rows.filter((a) => a.status !== "PENDING");
        return (
          <div className="space-y-6">
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
              {pending.length ? pending.map((a) => (
                <Card key={a.id} className={cn("border-l-[3px] p-4", a.risk_level === "CRITICAL" ? "border-l-critical" : "border-l-danger")}>
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2 text-[11.5px] font-semibold uppercase tracking-wider text-danger"><ShieldAlert className="h-3.5 w-3.5" />{a.risk_level}-risk action</div>
                    <span className="font-mono text-[12px] text-muted">{a.code}</span>
                  </div>
                  <div className="mt-1.5 text-[15px] font-semibold">{a.title}</div>
                  <KV className="mt-3" items={[
                    ["Reason", a.reason], ["Affected", Object.entries(a.affected ?? {}).map(([k, v]) => `${v} ${k}`).join(" · ") || "—"],
                    ["Evidence", a.evidence_refs?.join(", ") || "—"],
                    ["Finding", a.finding ? <Link to={`/findings/${a.finding.id}`} className="text-accent hover:underline">{a.finding.code} · {a.finding.control_code}</Link> : "—"],
                    ["Requested", `${fmtDateTime(a.created_at)} · ${a.requested_by_agent ? "Compliance Agent" : "Control owner"}`],
                    ["Required approver", <span className="font-mono text-[12px]">{a.required_permission}</span>],
                  ]} />
                  <div className="mt-3 flex flex-wrap gap-2">
                    <Button size="sm" variant="success" loading={busy === `${a.id}approve`} onClick={() => decide(a, "approve")}><CheckCircle2 className="h-3.5 w-3.5" />Approve</Button>
                    <Button size="sm" loading={busy === `${a.id}reject`} onClick={() => decide(a, "reject")}><XCircle className="h-3.5 w-3.5" />Reject</Button>
                    <Button size="sm" variant="ghost" loading={busy === `${a.id}request-changes`} onClick={() => decide(a, "request-changes")}>Request Changes</Button>
                    {!a.can_decide && <span className="self-center text-[11.5px] text-muted">Your role can't approve this — the backend will deny it.</span>}
                  </div>
                </Card>
              )) : <EmptyState title="No approvals waiting" description="Risky agent actions will appear here for a permitted human decision." />}
            </div>
            {!!decided.length && (
              <div>
                <div className="mb-2 text-[11.5px] font-semibold uppercase tracking-wider text-subtle">Decision history</div>
                <Card className="divide-y divide-border">
                  {decided.map((a) => (
                    <div key={a.id} className="flex flex-wrap items-center gap-3 px-4 py-2.5 text-[13px]">
                      <span className="font-mono text-[12px] text-muted">{a.code}</span><span className="min-w-0 flex-1">{a.title}</span>
                      <RiskBadge risk={a.risk_level} /><StatusBadge status={a.status} /><span className="text-[12px] text-muted">{fmtDate(a.decided_at)}</span>
                    </div>
                  ))}
                </Card>
              </div>
            )}
          </div>
        );
      }}
    </QueryView>
  );
}

function Plans() {
  const q = useQuery({ queryKey: ["remediation"], queryFn: () => api.get<any[]>("/api/remediation") });
  const qc = useQueryClient();
  const { can, user } = useAuth();
  const [show, setShow] = React.useState<"active" | "completed">("active");
  const complete = async (t: any) => {
    try { await api.post(`/api/remediation/tasks/${t.id}`, { status: "COMPLETED" }); toast.success("Task completed"); qc.invalidateQueries({ queryKey: ["remediation"] }); }
    catch (e) { toast.error((e as ApiError).message); }
  };
  const verify = async (pl: any) => {
    try { const r = await api.post<any>(`/api/remediation/${pl.id}/verify`); toast[r.result === "PASSED" ? "success" : "warning"](`Verification ${r.result}${r.message ? ` — ${r.message}` : ""}`); ["remediation", "findings", "controls", "dashboard"].forEach((k) => qc.invalidateQueries({ queryKey: [k] })); }
    catch (e) { toast.error((e as ApiError).message); }
  };
  return (
    <QueryView q={q} empty={<EmptyState title="No remediation plans" />}>
      {(rows) => {
        const list = rows.filter((p) => (show === "active" ? !["COMPLETED", "CANCELLED"].includes(p.status) : p.status === "COMPLETED"));
        return (
          <>
            <div className="mb-3 flex gap-2">
              {(["active", "completed"] as const).map((k) => (
                <button key={k} onClick={() => setShow(k)} className={cn("rounded-lg border px-3 py-1.5 text-[12.5px] font-medium cursor-pointer", show === k ? "border-accent bg-accent-soft text-accent" : "border-border text-muted")}>
                  {k === "active" ? "Active" : "Completed"} <span className="tabular opacity-70">{rows.filter((p) => (k === "active" ? !["COMPLETED", "CANCELLED"].includes(p.status) : p.status === "COMPLETED")).length}</span>
                </button>
              ))}
            </div>
            <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
              {list.slice(0, 40).map((pl) => (
                <Card key={pl.id} className="p-4">
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div className="min-w-0">
                      <div className="text-[11.5px] text-muted"><span className="font-mono">{pl.code}</span>{pl.finding && <> · <Link to={`/findings/${pl.finding.id}`} className="hover:underline">{pl.finding.code}</Link> · {pl.finding.control_code}</>}{pl.created_by_agent && <Badge tone="accent" className="ml-2">Agent-generated</Badge>}</div>
                      <div className="mt-0.5 text-[14px] font-semibold">{pl.title}</div>
                    </div>
                    <StatusBadge status={pl.status} />
                  </div>
                  <Progress value={pl.progress} tone={pl.status === "COMPLETED" ? "success" : "accent"} className="mt-3" />
                  <ul className="mt-3 divide-y divide-border text-[12.5px]">
                    {pl.tasks.map((t: any) => (
                      <li key={t.id} className="flex flex-wrap items-center gap-2 py-1.5">
                        <span className="w-4 text-muted tabular">{t.seq}</span>
                        <span className="min-w-0 flex-1">{t.title}<span className="block text-[11px] text-subtle">{t.owner ?? "Unassigned"} · due {fmtDate(t.due_date, { day: "2-digit", month: "short" })} · evidence: {t.evidence_required}</span></span>
                        <RiskBadge risk={t.risk} /><StatusBadge status={t.overdue ? "OVERDUE" : t.status} />
                        {can("REMEDIATION_EXECUTE") && !t.action_type && ["PENDING", "IN_PROGRESS"].includes(t.status) && t.risk === "LOW" && (t.owner_id === user?.id || can("REMEDIATION_CREATE")) && (
                          <Button size="sm" variant="ghost" onClick={() => complete(t)}>Complete</Button>
                        )}
                      </li>
                    ))}
                  </ul>
                  {["VERIFYING", "FAILED", "IN_PROGRESS"].includes(pl.status) && pl.created_by_agent && (
                    <div className="mt-2"><Button size="sm" onClick={() => verify(pl)}>Run verification</Button></div>
                  )}
                </Card>
              ))}
            </div>
          </>
        );
      }}
    </QueryView>
  );
}

export default function Remediation() {
  const [p, setP] = useSearchParams();
  const { can } = useAuth();
  return (
    <>
      <PageHeader eyebrow="Remediation" title="Remediation & approvals" description="Multi-step plans with owners, dependencies and required evidence. Medium, high and critical actions wait for a permitted human decision." />
      <Tabs value={p.get("tab") ?? (can("REMEDIATION_READ") ? "plans" : "plans")} onValueChange={(v) => setP({ tab: v })}>
        <TabsList><TabsTrigger value="plans">Plans</TabsTrigger>{(can("REMEDIATION_READ") || can("APPROVAL_MEDIUM")) && <TabsTrigger value="approvals">Approvals</TabsTrigger>}</TabsList>
        <TabsContent value="plans"><Plans /></TabsContent>
        <TabsContent value="approvals"><Approvals /></TabsContent>
      </Tabs>
    </>
  );
}

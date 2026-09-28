import * as React from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { KV, PageHeader, QueryView, StatusBadge } from "@/components/app";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/hooks/useAuth";
import { api, ApiError } from "@/lib/api";
import { title } from "@/lib/utils";

export default function Settings() {
  const q = useQuery({ queryKey: ["settings"], queryFn: () => api.get<any>("/api/settings") });
  const usage = useQuery({ queryKey: ["ai-usage"], queryFn: () => api.get<any>("/api/ai-usage"), retry: false });
  const qc = useQueryClient();
  const { user } = useAuth();
  const [weights, setWeights] = React.useState<Record<string, number> | null>(null);
  const [thr, setThr] = React.useState<Record<string, number> | null>(null);
  React.useEffect(() => { if (q.data) { setWeights(q.data.risk_model.weights); setThr(q.data.risk_model.thresholds); } }, [q.data]);
  const refresh = () => ["settings", "dashboard", "controls", "nav-counts"].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
  const save = async () => {
    try { await api.put("/api/settings/risk-model", { weights, thresholds: thr }); toast.success("Risk model updated — scores recalculated"); refresh(); }
    catch (e) { toast.error((e as ApiError).message); }
  };
  const fault = async (connector: string, enabled: boolean) => {
    try { await api.put("/api/settings/fault-injection", { connector, enabled }); toast.message(`${connector} ${enabled ? "unavailable (simulated)" : "restored"}`); refresh(); }
    catch (e) { toast.error((e as ApiError).message); }
  };
  return (
    <>
      <PageHeader eyebrow="Settings" title="Settings" description="Risk model configuration, connectors, model routing and demo simulations." />
      <QueryView q={q}>
        {(s) => (
          <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
            <Card><CardHeader title="NovaTech Prototype Risk Model" description="Score = 100 × Severity × Likelihood × Criticality × Evidence freshness × Recurrence (weights are exponents). Not an official regulatory formula." />
              <CardBody className="space-y-4">
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
                  {weights && Object.entries(weights).map(([k, v]) => (
                    <label key={k} className="text-[12px] text-muted">{title(k)}<Input type="number" step="0.1" min={0} max={3} value={v} disabled={!s.can_manage} onChange={(e) => setWeights({ ...weights, [k]: Number(e.target.value) })} /></label>
                  ))}
                </div>
                <div className="grid grid-cols-3 gap-3">
                  {thr && (["MEDIUM", "HIGH", "CRITICAL"] as const).map((k) => (
                    <label key={k} className="text-[12px] text-muted">{title(k)} ≥<Input type="number" min={1} max={100} value={thr[k]} disabled={!s.can_manage} onChange={(e) => setThr({ ...thr, [k]: Number(e.target.value) })} /></label>
                  ))}
                </div>
                {s.can_manage ? (
                  <div className="flex gap-2"><Button variant="primary" onClick={save}>Save & recalculate</Button><Button onClick={async () => { await api.post("/api/settings/risk-model/reset"); toast.success("Risk model reset"); refresh(); }}>Reset to default</Button></div>
                ) : <p className="text-[12px] text-muted">Your role ({user?.role_name}) can view but not change the risk model.</p>}
              </CardBody>
            </Card>
            <Card><CardHeader title="AI engine & model routing" description="Model names come from environment variables only" /><CardBody>
              <KV items={[
                ["Engine", <Badge tone={s.model_routing.llm_enabled ? "success" : "accent"}>{s.model_routing.llm_enabled ? "OpenAI Agents SDK" : "Deterministic engine"}</Badge>],
                ["Reasoning model", <span className="font-mono text-[12px]">{s.model_routing.routes.reasoning}</span>],
                ["Fast model", <span className="font-mono text-[12px]">{s.model_routing.routes.fast}</span>],
                ["Embeddings", <span className="font-mono text-[12px]">{s.model_routing.embedding_provider} · {s.model_routing.routes.embedding}</span>],
              ]} />
              <p className="mt-3 text-[12px] text-muted">Without OPENAI_API_KEY / OPENAI_MODEL every workflow still runs on backend tools and rules. With them, intent classification, narratives and grounded answers use structured outputs, and free-form questions run through the Agents SDK — every tool call still passes the Tool Gateway.</p>
              {usage.data && (
                <div className="mt-4 grid grid-cols-2 gap-2 text-[12.5px] sm:grid-cols-3">
                  {[["Agent runs", usage.data.agent_runs], ["Success rate", usage.data.success_rate != null ? `${usage.data.success_rate}%` : "—"], ["Avg run", usage.data.avg_run_ms != null ? `${(usage.data.avg_run_ms / 1000).toFixed(1)}s` : "—"],
                    ["Model calls", usage.data.model_calls], ["Tool calls", usage.data.tool_calls], ["Tool denials", usage.data.tool_denials]].map(([k, v]) => (
                    <div key={k as string} className="rounded-lg bg-surface-2 px-3 py-2"><div className="text-muted">{k}</div><div className="text-[16px] font-semibold tabular">{v}</div></div>
                  ))}
                  <div className="col-span-full text-[11px] text-subtle">Estimated cost ${usage.data.estimated_cost_usd} — {usage.data.label}.</div>
                </div>
              )}
            </CardBody></Card>
            <Card><CardHeader title="Connector gateway" description="Business logic calls a connector interface (get_data / create_action / update_data / verify_action)" /><CardBody className="space-y-2">
              {s.connectors.map((c: any) => (
                <div key={c.key} className="flex items-center justify-between gap-2 rounded-lg border border-border px-3 py-2 text-[13px]">
                  <div><div className="font-medium">{c.name}</div><div className="text-[11.5px] text-muted">{title(c.kind)}</div></div>
                  <StatusBadge status={c.status} />
                </div>
              ))}
            </CardBody></Card>
            <Card><CardHeader title="Demo simulations" description="Fault injection to demonstrate self-recovery and fail-safe verification" /><CardBody className="space-y-3">
              {["evidence_store", "iam"].map((k) => {
                const on = !!s.fault_injection[k];
                return (
                  <div key={k} className="flex items-center justify-between gap-3 rounded-lg border border-border px-3 py-2.5 text-[13px]">
                    <div><div className="font-medium">{k === "iam" ? "IAM Demo Connector unavailable" : "Evidence service unavailable"}</div><div className="text-[11.5px] text-muted">Agent retries, records the failure and never claims success.</div></div>
                    <Button size="sm" variant={on ? "danger" : "secondary"} disabled={!s.can_manage} onClick={() => fault(k, !on)}>{on ? "On — restore" : "Simulate outage"}</Button>
                  </div>
                );
              })}
              <KV items={[["Environment", <Badge tone="accent">DEMO</Badge>], ["Email", "Demo Email Service"], ["SSO", "Demo SAML SSO"], ["WAF / DDoS", "Prototype Simulation"]]} />
            </CardBody></Card>
          </div>
        )}
      </QueryView>
    </>
  );
}

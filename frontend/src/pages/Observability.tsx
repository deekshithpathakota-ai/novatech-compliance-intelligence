import { useQuery } from "@tanstack/react-query";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { DataTable, MetricCard, PageHeader, QueryView, StatusBadge } from "@/components/app";
import { Badge } from "@/components/ui/badge";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { api } from "@/lib/api";
import { fmtDate, fmtDateTime, title } from "@/lib/utils";

const tip = { contentStyle: { background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 12, color: "var(--foreground)" }, cursor: { fill: "var(--surface-2)" } };
const axis = { tick: { fontSize: 11, fill: "var(--muted)" }, axisLine: false, tickLine: false } as const;
const ms = (v: number | null) => (v == null ? "—" : v >= 1000 ? `${(v / 1000).toFixed(1)}s` : `${v}ms`);

export default function Observability() {
  const q = useQuery({ queryKey: ["observability"], queryFn: () => api.get<any>("/api/observability"), refetchInterval: 20000 });
  return (
    <>
      <PageHeader eyebrow="Operations" title="Observability & AI usage" description="Agent runs, tool calls, retrieval, verification, approvals and model usage — from OpenTelemetry-compatible spans and DB-backed run metrics." />
      <QueryView q={q}>
        {(d) => {
          const k = d.kpis;
          return (
            <div className="space-y-5">
              <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-8">
                <MetricCard label="Agent runs" value={k.agent_runs} tone="info" />
                <MetricCard label="Success rate" value={k.success_rate != null ? `${k.success_rate}%` : "—"} tone="success" />
                <MetricCard label="Avg run time" value={ms(k.avg_run_ms)} hint={`p95 ${ms(k.p95_run_ms)}`} />
                <MetricCard label="Tool calls" value={k.tool_calls} hint={`${k.tool_denials} denied`} />
                <MetricCard label="Tool failures" value={k.tool_failures} tone={k.tool_failures ? "danger" : "neutral"} />
                <MetricCard label="Verification failures" value={k.verification_failures} hint={`of ${k.verifications}`} tone={k.verification_failures ? "warning" : "neutral"} />
                <MetricCard label="Retrieval latency" value={k.retrieval_avg_ms != null ? `${k.retrieval_avg_ms}ms` : "—"} hint="search_documents avg" />
                <MetricCard label="Approval wait" value={k.approval_wait_min != null ? `${k.approval_wait_min}m` : "—"} hint="agent requests → decision" />
              </div>
              <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
                <Card><CardHeader title="Agent runs per day" description="Last 14 days" /><CardBody className="h-[220px]">
                  <ResponsiveContainer><BarChart data={d.runs_per_day} margin={{ left: -18, right: 8 }}>
                    <CartesianGrid vertical={false} stroke="var(--border)" /><XAxis dataKey="date" {...axis} tickFormatter={(s) => fmtDate(s, { day: "2-digit", month: "short" })} />
                    <YAxis {...axis} allowDecimals={false} /><Tooltip {...tip} labelFormatter={(s) => fmtDate(String(s))} />
                    <Bar dataKey="runs" fill="var(--accent)" radius={[4, 4, 0, 0]} maxBarSize={28} />
                  </BarChart></ResponsiveContainer>
                </CardBody></Card>
                <Card><CardHeader title="LLM usage" description={d.cost_label} action={<Badge tone="accent">{d.cost_label}</Badge>} /><CardBody className="space-y-2 text-[13px]">
                  {[["Model calls", k.llm_calls], ["Tokens in", k.tokens_in.toLocaleString()], ["Tokens out", k.tokens_out.toLocaleString()], ["Estimated cost", `$${k.estimated_cost_usd}`]].map(([a, b]) => (
                    <div key={a as string} className="flex justify-between"><span className="text-muted">{a}</span><b className="tabular">{b}</b></div>
                  ))}
                  <div className="pt-2"><div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-subtle">Runs by intent</div>
                    <div className="flex flex-wrap gap-1.5">{d.runs_by_intent.map((r: any) => <Badge key={r.intent} tone="neutral" className="normal-case tracking-normal">{title(r.intent)} · {r.count}</Badge>)}</div></div>
                  <p className="pt-2 text-[11.5px] text-subtle">{d.label}</p>
                </CardBody></Card>
              </div>
              <div className="grid grid-cols-1 gap-5 lg:grid-cols-[minmax(0,1fr)_320px]">
                <DataTable dense rows={d.tools} rowKey={(r: any) => r.tool} columns={[
                  { key: "t", header: "Tool", cell: (r: any) => <span className="font-mono text-[12px]">{r.tool}</span> },
                  { key: "c", header: "Calls", cell: (r: any) => r.calls },
                  { key: "f", header: "Failures", cell: (r: any) => <span className={r.failures ? "text-danger" : ""}>{r.failures}</span> },
                  { key: "d", header: "Denied", cell: (r: any) => <span className={r.denials ? "text-warning" : ""}>{r.denials}</span> },
                  { key: "ms", header: "Avg", cell: (r: any) => `${r.avg_ms} ms` },
                ]} />
                <Card><CardHeader title="Streamed events" /><CardBody className="space-y-1">
                  {d.events.map((e: any) => <div key={e.event} className="flex justify-between text-[12.5px]"><span className="font-mono text-muted">{e.event}</span><b className="tabular">{e.count}</b></div>)}
                </CardBody></Card>
              </div>
              <DataTable rows={d.recent_runs} rowKey={(r: any) => r.id} columns={[
                { key: "id", header: "Run", cell: (r: any) => <span className="font-mono text-[12px] text-muted">#{r.id}</span> },
                { key: "o", header: "Objective", cell: (r: any) => r.objective },
                { key: "i", header: "Intent", cell: (r: any) => title(r.intent) },
                { key: "e", header: "Engine", hideOnMobile: true, cell: (r: any) => r.engine },
                { key: "at", header: "Started", hideOnMobile: true, cell: (r: any) => fmtDateTime(r.started_at) },
                { key: "d", header: "Duration", cell: (r: any) => ms(r.duration_ms) },
                { key: "s", header: "Status", cell: (r: any) => <StatusBadge status={r.status} /> },
              ]} />
            </div>
          );
        }}
      </QueryView>
    </>
  );
}

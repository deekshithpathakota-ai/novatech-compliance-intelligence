import * as React from "react";
import { useNavigate } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { KV, PageHeader, QueryView, RiskBadge, StatusBadge } from "@/components/app";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Select } from "@/components/ui/input";
import { api } from "@/lib/api";
import { cn, title } from "@/lib/utils";
import type { ControlRow } from "@/types";

const COL_W = 156, NODE_H = 46, GAP_Y = 10, PAD = 12;
const KIND_COLOR: Record<string, string> = {
  requirement: "var(--info)", control: "var(--primary)", evidence: "var(--success)", test: "var(--muted)",
  finding: "var(--danger)", remediation: "var(--accent)", verification: "var(--success)",
};

export default function ComplianceGraph() {
  const nav = useNavigate();
  const controls = useQuery({ queryKey: ["controls", ""], queryFn: () => api.get<ControlRow[]>("/api/controls") });
  const [focus, setFocus] = React.useState("");
  const [fw, setFw] = React.useState("");
  const qs = new URLSearchParams();
  if (focus) qs.set("focus", focus);
  if (fw) qs.set("framework", fw);
  const q = useQuery({ queryKey: ["graph", focus, fw], queryFn: () => api.get<any>(`/api/graph?${qs}`) });
  const [sel, setSel] = React.useState<any>(null);
  const [hover, setHover] = React.useState<string | null>(null);
  return (
    <>
      <PageHeader eyebrow="Intelligence Lab" title="Compliance Graph" description="The knowledge model as a graph: requirement → control → evidence → test → finding → remediation → verification. Click any node to inspect it." />
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <Select aria-label="Focus control" value={focus} onChange={(e) => { setFocus(e.target.value); setSel(null); }}>
          <option value="">Controls needing attention</option>
          {controls.data?.map((c) => <option key={c.code} value={c.code}>{c.code} · {c.name}</option>)}
        </Select>
        <Select aria-label="Framework" value={fw} onChange={(e) => setFw(e.target.value)}><option value="">All frameworks</option>{["ISO27001", "SOC2", "NIST_CSF", "DPDP"].map((f) => <option key={f}>{f}</option>)}</Select>
        {q.data && <span className="text-[12px] text-muted">{q.data.nodes.length} nodes · {q.data.edges.length} edges</span>}
      </div>
      <QueryView q={q}>
        {(g) => {
          const pos: Record<string, { x: number; y: number }> = {};
          let maxRows = 0;
          g.layers.forEach((k: string, ci: number) => {
            const ns = g.nodes.filter((n: any) => n.kind === k);
            maxRows = Math.max(maxRows, ns.length);
            ns.forEach((n: any, ri: number) => (pos[n.id] = { x: PAD + ci * (COL_W + 26), y: 34 + ri * (NODE_H + GAP_Y) }));
          });
          const W = PAD * 2 + g.layers.length * (COL_W + 26), H = 34 + maxRows * (NODE_H + GAP_Y) + PAD;
          const linked = new Set<string>();
          if (hover) g.edges.forEach((e: any) => { if (e.from === hover || e.to === hover) { linked.add(e.from); linked.add(e.to); } });
          return (
            <div className="grid grid-cols-1 gap-4 2xl:grid-cols-[minmax(0,1fr)_300px]">
              <Card className="overflow-auto scrollbar-thin p-2" style={{ maxHeight: "72vh" }}>
                <svg width={W} height={H} role="img" aria-label="Compliance knowledge graph">
                  {g.layers.map((k: string, ci: number) => (
                    <text key={k} x={PAD + ci * (COL_W + 26)} y={18} fontSize={10.5} fontWeight={600} fill="var(--subtle)" style={{ textTransform: "uppercase", letterSpacing: ".06em" }}>{k}</text>
                  ))}
                  {g.edges.map((e: any, i: number) => {
                    const a = pos[e.from], b = pos[e.to];
                    if (!a || !b) return null;
                    const x1 = a.x + COL_W, y1 = a.y + NODE_H / 2, x2 = b.x, y2 = b.y + NODE_H / 2;
                    const back = x2 <= x1;
                    const d = back ? `M${a.x + COL_W / 2} ${a.y + NODE_H} C ${a.x + COL_W / 2} ${a.y + NODE_H + 30}, ${b.x + COL_W / 2} ${b.y + NODE_H + 30}, ${b.x + COL_W / 2} ${b.y + NODE_H}`
                      : `M${x1} ${y1} C ${x1 + 18} ${y1}, ${x2 - 18} ${y2}, ${x2} ${y2}`;
                    const on = hover && (e.from === hover || e.to === hover);
                    return <path key={i} d={d} fill="none" stroke={on ? "var(--accent)" : "var(--border-strong)"} strokeWidth={on ? 1.8 : 1} opacity={hover && !on ? 0.25 : 1} />;
                  })}
                  {g.nodes.map((n: any) => {
                    const p = pos[n.id];
                    const dim = hover && !linked.has(n.id);
                    return (
                      <g key={n.id} transform={`translate(${p.x},${p.y})`} style={{ cursor: "pointer" }} opacity={dim ? 0.3 : 1}
                        onClick={() => setSel(n)} onMouseEnter={() => setHover(n.id)} onMouseLeave={() => setHover(null)}
                        tabIndex={0} role="button" aria-label={`${n.kind} ${n.label}`} onKeyDown={(e) => e.key === "Enter" && setSel(n)}>
                        <rect width={COL_W} height={NODE_H} rx={8} fill="var(--surface)" stroke={sel?.id === n.id ? "var(--accent)" : "var(--border-strong)"} strokeWidth={sel?.id === n.id ? 2 : 1} />
                        <rect width={4} height={NODE_H} rx={2} fill={KIND_COLOR[n.kind]} />
                        <text x={12} y={18} fontSize={11.5} fontWeight={600} fill="var(--foreground)" fontFamily="JetBrains Mono, monospace">{n.label}</text>
                        <text x={12} y={34} fontSize={10.5} fill="var(--muted)">{(n.sub ?? "").slice(0, 23)}{(n.sub ?? "").length > 23 ? "…" : ""}</text>
                        {n.status && <circle cx={COL_W - 12} cy={14} r={4.5} fill={/PASS|VALID|PASSED|CLOSED|COMPLETED|ACTIVE/.test(n.status) ? "var(--success)" : /FAIL|OVERDUE|EXPIRED|OPEN|MISSING|CONFLICT|CHANGED/.test(n.status) ? "var(--danger)" : "var(--warning)"} />}
                      </g>
                    );
                  })}
                </svg>
              </Card>
              <Card className="h-fit p-4">
                {sel ? (
                  <div className="space-y-3">
                    <div className="text-[11px] font-semibold uppercase tracking-wider text-subtle">{title(sel.kind)}</div>
                    <div className="font-mono text-[15px] font-semibold">{sel.label}</div>
                    <div className="text-[13px]">{sel.sub}</div>
                    <KV items={[["Status", <StatusBadge status={sel.status} />], ...(sel.risk ? [["Risk", <RiskBadge risk={sel.risk} score={sel.score} />] as [string, React.ReactNode]] : []),
                      ...(sel.severity ? [["Severity", <RiskBadge risk={sel.severity} />] as [string, React.ReactNode]] : []),
                      ["Connections", g.edges.filter((e: any) => e.from === sel.id || e.to === sel.id).length]]} />
                    <div className="flex flex-wrap gap-2">
                      {sel.link && <Button size="sm" variant="primary" onClick={() => nav(sel.link)}>Open</Button>}
                      {sel.kind === "control" && <Button size="sm" onClick={() => setFocus(sel.label)}>Focus graph</Button>}
                    </div>
                  </div>
                ) : <p className="text-[13px] text-muted">Select a node to inspect it. Hover to trace its connections.</p>}
                <div className="mt-4 space-y-1 border-t border-border pt-3">
                  {g.layers.map((k: string) => <div key={k} className="flex items-center gap-2 text-[12px]"><span className="h-2.5 w-2.5 rounded-sm" style={{ background: KIND_COLOR[k] }} /><span className={cn("flex-1", !g.counts[k] && "text-subtle")}>{title(k)}</span><span className="tabular text-muted">{g.counts[k] ?? 0}</span></div>)}
                </div>
              </Card>
            </div>
          );
        }}
      </QueryView>
    </>
  );
}

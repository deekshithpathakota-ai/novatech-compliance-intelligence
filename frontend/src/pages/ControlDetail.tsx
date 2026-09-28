import * as React from "react";
import { Link, useNavigate, useParams } from "react-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Beaker, FlaskConical, Repeat, Sparkles } from "lucide-react";
import { toast } from "sonner";
import { DataTable, KV, PageHeader, QueryView, RiskBadge, StatusBadge, Timeline, WhyButton } from "@/components/app";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useAuth } from "@/hooks/useAuth";
import { api, ApiError } from "@/lib/api";
import { cn, fmtDate, title } from "@/lib/utils";

const KIND_ORDER = [["requirement", "control", "test", "evidence", "document"], ["finding", "remediation", "verification"]];
const KIND_STYLE: Record<string, string> = {
  requirement: "border-info/40 bg-info-soft", control: "border-primary/40 bg-primary-soft", test: "border-border-strong bg-surface-2",
  evidence: "border-success/40 bg-success-soft", document: "border-border bg-surface", finding: "border-danger/40 bg-danger-soft",
  remediation: "border-accent/40 bg-accent-soft", verification: "border-success/40 bg-success-soft",
};

export function LineageGraph({ lineage }: { lineage: { nodes: any[]; edges: any[] } }) {
  const nav = useNavigate();
  return (
    <div className="space-y-5 overflow-x-auto scrollbar-thin pb-2">
      {KIND_ORDER.map((row, ri) => (
        <div key={ri} className="flex min-w-max items-stretch gap-2">
          {ri === 1 && <div className="w-[170px] self-center text-right text-[11px] font-semibold uppercase tracking-wider text-subtle">Control history →</div>}
          {row.map((kind, ci) => {
            const nodes = lineage.nodes.filter((n) => n.kind === kind);
            if (!nodes.length) return null;
            return (
              <React.Fragment key={kind}>
                {ci > 0 && <ArrowRight className="h-4 w-4 shrink-0 self-center text-subtle" />}
                <div className="flex w-[170px] flex-col gap-1.5">
                  <div className="text-[10.5px] font-semibold uppercase tracking-wider text-subtle">{kind}</div>
                  {nodes.map((n) => (
                    <button key={n.id} onClick={() => n.link && nav(n.link)} className={cn("rounded-lg border px-2.5 py-2 text-left text-[12px] transition-shadow hover:shadow-pop", KIND_STYLE[kind], n.link ? "cursor-pointer" : "cursor-default")}>
                      <div className="flex items-center justify-between gap-1"><span className="font-mono font-semibold">{n.label}</span>{n.status && <StatusBadge status={n.status} className="scale-90 origin-right" />}</div>
                      <div className="mt-0.5 line-clamp-2 text-muted">{n.sub}</div>
                    </button>
                  ))}
                </div>
              </React.Fragment>
            );
          })}
        </div>
      ))}
    </div>
  );
}

export default function ControlDetail() {
  const { id } = useParams();
  const nav = useNavigate();
  const qc = useQueryClient();
  const { can } = useAuth();
  const q = useQuery({ queryKey: ["controls", "detail", id], queryFn: () => api.get<any>(`/api/controls/${id}`) });
  const [test, setTest] = React.useState<any>(null);
  const [busy, setBusy] = React.useState(false);
  const runTest = async () => {
    setBusy(true);
    try {
      const r = await api.post<any>(`/api/controls/${id}/test`);
      setTest(r);
      qc.invalidateQueries({ queryKey: ["controls"] });
      qc.invalidateQueries({ queryKey: ["nav-counts"] });
    } catch (e) { toast.error((e as ApiError).message); } finally { setBusy(false); }
  };
  return (
    <QueryView q={q}>
      {(c) => {
        const open = c.findings.find((f: any) => ["OPEN", "IN_REMEDIATION"].includes(f.status));
        return (
          <>
            <PageHeader
              eyebrow={<Link to="/controls" className="hover:underline">Controls</Link>}
              title={<span className="flex flex-wrap items-center gap-3"><span className="font-mono text-muted">{c.code}</span>{c.name}</span>}
              description={c.description}
              actions={<>
                <WhyButton kind="control" code={c.code} />
                {can("AGENT_USE") && <Button onClick={() => nav(`/agent?q=${encodeURIComponent(`Investigate ${c.code}`)}`)}><Sparkles className="h-3.5 w-3.5 text-accent" />Investigate</Button>}
                {can("CONTROL_TEST_RUN") && <Button onClick={runTest} loading={busy}><FlaskConical className="h-3.5 w-3.5" />Test control</Button>}
                {open && can("REMEDIATION_CREATE") && <Button variant="primary" onClick={() => nav(`/agent?q=${encodeURIComponent(`Create a remediation plan for ${open.code}`)}`)}>Generate Remediation</Button>}
              </>}
            />
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-5">
              {[
                ["Status", <StatusBadge status={c.status} />], ["Risk", <RiskBadge risk={c.risk_category} score={c.risk_score} />],
                ["Last tested", <span>{c.days_since_test != null ? `${c.days_since_test} days ago` : "Never"}</span>],
                ["Required", <span>every {c.frequency_days} days</span>], ["Evidence", <StatusBadge status={c.evidence_status} />],
              ].map(([k, v], i) => (
                <Card key={i} className="px-4 py-3"><div className="text-[12px] text-muted">{k}</div><div className="mt-1 text-[15px] font-semibold">{v}</div></Card>
              ))}
            </div>
            {c.recurring && (
              <div className="mt-3 flex flex-wrap items-center gap-2 rounded-card border border-danger/30 bg-danger-soft px-4 py-3 text-[13px] text-danger">
                <Repeat className="h-4 w-4" /><b>Recurring finding:</b> {c.recurring.occurrences} occurrences since {fmtDate(c.recurring.first_detected)} · previous remediation {c.recurring.previous_remediation.toLowerCase()} · {c.recurring.verification_summary.toLowerCase()} · effectiveness {c.recurring.effectiveness.level}
              </div>
            )}
            <Tabs defaultValue="overview" className="mt-5">
              <TabsList>
                {["overview", "evidence", "tests", "findings", "lineage", "timeline", "memory"].map((t) => <TabsTrigger key={t} value={t}>{title(t)}</TabsTrigger>)}
              </TabsList>
              <TabsContent value="overview">
                <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
                  <Card><CardHeader title="Control" /><CardBody>
                    <KV items={[
                      ["Frameworks", c.frameworks.join(", ") || "—"], ["Requirements", c.requirements_detail.map((r: any) => `${r.code} v${r.version}`).join(", ") || "—"],
                      ["Owner", c.owner ?? "Unassigned"], ["Department", c.department], ["Frequency", `${c.frequency_days} days`], ["Criticality", `${c.criticality}/5`],
                      ["Automation", title(c.automation)], ["Next test", fmtDate(c.next_test)], ["Historical failures", c.historical_failures],
                    ]} />
                    {c.misaligned && <p className="mt-3 rounded-lg bg-danger-soft px-3 py-2 text-[12.5px] text-danger">Potential control drift: {c.misaligned.requirement} v{c.misaligned.version} requires every {c.misaligned.required_interval_days} days; this control runs every {c.misaligned.control_interval_days} days.</p>}
                  </CardBody></Card>
                  <Card><CardHeader title="Control Health Timeline" description="Every recorded test result" /><CardBody>
                    <div className="flex flex-wrap gap-1.5">
                      {c.health_history.map((h: any, i: number) => (
                        <div key={i} title={`${fmtDate(h.date)} · ${h.result}`} className={cn("h-6 w-6 rounded-md", h.result === "PASS" ? "bg-success" : h.result === "FAIL" ? "bg-danger" : "bg-warning")} />
                      ))}
                    </div>
                    <div className="mt-2 flex justify-between text-[11px] text-muted"><span>{fmtDate(c.health_history[0]?.date)}</span><span>{fmtDate(c.health_history.at(-1)?.date)}</span></div>
                    <div className="mt-4 text-[11px] font-semibold uppercase tracking-wider text-subtle">Owner history</div>
                    <ul className="mt-1 space-y-1 text-[12.5px]">{c.owner_history.map((o: any, i: number) => <li key={i}>{o.name} <span className="text-muted">· {fmtDate(o.from)} → {o.to ? fmtDate(o.to) : "present"}</span></li>)}</ul>
                    <div className="mt-4 text-[11px] font-semibold uppercase tracking-wider text-subtle">Test procedure</div>
                    <ul className="mt-1 list-disc pl-5 text-[12.5px] text-muted">{c.test_procedure.map((t: string) => <li key={t}>{t}</li>)}</ul>
                  </CardBody></Card>
                </div>
              </TabsContent>
              <TabsContent value="evidence">
                <DataTable rows={c.evidence} rowKey={(e: any) => e.id} onRowClick={(e: any) => nav(`/evidence?focus=${e.id}`)}
                  empty={<div className="rounded-card border border-dashed border-border-strong p-8 text-center text-[13px] text-muted">No evidence has been submitted for this control.</div>}
                  columns={[
                    { key: "c", header: "Evidence", cell: (e: any) => <span className="font-mono text-[12px] text-muted">{e.code}</span> },
                    { key: "n", header: "Name", cell: (e: any) => e.name },
                    { key: "col", header: "Collected", cell: (e: any) => fmtDate(e.collected_at) },
                    { key: "v", header: "Valid until", cell: (e: any) => fmtDate(e.valid_until) },
                    { key: "f", header: "Freshness", cell: (e: any) => <StatusBadge status={e.freshness.label} /> },
                    { key: "s", header: "Status", cell: (e: any) => <StatusBadge status={e.status} /> },
                  ]} />
              </TabsContent>
              <TabsContent value="tests">
                <DataTable rows={c.tests} rowKey={(t: any) => t.id} columns={[
                  { key: "c", header: "Test", cell: (t: any) => <span className="font-mono text-[12px] text-muted">{t.code}</span> },
                  { key: "d", header: "Date", cell: (t: any) => fmtDate(t.tested_at) },
                  { key: "m", header: "Method", cell: (t: any) => t.method },
                  { key: "by", header: "Tested by", cell: (t: any) => title(t.tester_type) },
                  { key: "n", header: "Notes", hideOnMobile: true, cell: (t: any) => <span className="text-muted">{t.notes || "—"}</span> },
                  { key: "r", header: "Result", cell: (t: any) => <StatusBadge status={t.result} /> },
                ]} />
              </TabsContent>
              <TabsContent value="findings">
                <DataTable rows={c.findings} rowKey={(f: any) => f.id} onRowClick={(f: any) => nav(`/findings/${f.id}`)} columns={[
                  { key: "c", header: "Finding", cell: (f: any) => <span className="font-mono text-[12px] text-muted">{f.code}</span> },
                  { key: "t", header: "Title", cell: (f: any) => f.title },
                  { key: "a", header: "Audit", hideOnMobile: true, cell: (f: any) => f.audit?.name ?? "Continuous monitoring" },
                  { key: "d", header: "Detected", cell: (f: any) => fmtDate(f.detected_at) },
                  { key: "s", header: "Severity", cell: (f: any) => <RiskBadge risk={f.severity} /> },
                  { key: "st", header: "Status", cell: (f: any) => <StatusBadge status={f.status} /> },
                ]} />
              </TabsContent>
              <TabsContent value="lineage">
                <Card><CardHeader title="Evidence lineage" description="Requirement → control → test → evidence → document page, and the finding → remediation → verification chain. Click a node to open it." />
                  <CardBody><LineageGraph lineage={c.lineage} /></CardBody></Card>
              </TabsContent>
              <TabsContent value="timeline"><Card className="p-5"><Timeline items={c.timeline} /></Card></TabsContent>
              <TabsContent value="memory">
                <div className="space-y-2">
                  {c.memory.map((m: any) => (
                    <Card key={m.id} className="px-4 py-3 text-[13px]">
                      <div className="flex flex-wrap items-center gap-2"><Badge tone="accent">{m.category}</Badge><span className="text-muted">{fmtDate(m.occurred_at)} · {m.source_label}</span>{m.verification && <StatusBadge status={m.verification} />}</div>
                      <div className="mt-1">{m.summary}</div>
                      {m.current_relevance && <div className="mt-1 text-[12.5px] text-accent">Current relevance: {m.current_relevance}</div>}
                    </Card>
                  ))}
                </div>
              </TabsContent>
            </Tabs>

            <Dialog open={!!test} onOpenChange={(o) => !o && setTest(null)}>
              <DialogContent title={`Control test ${test?.test?.code ?? ""} · ${c.code}`} description="Each answer is derived from evidence facts — nothing is assumed.">
                {test && (
                  <div className="space-y-3">
                    <div className="flex items-center gap-3"><Beaker className="h-4 w-4 text-accent" /><StatusBadge status={test.result} /><span className="text-[12.5px] text-muted">{test.coverage} · evidence quality {test.evidence_quality} · {test.source_count} sources</span></div>
                    <ul className="divide-y divide-border rounded-lg border border-border">
                      {test.questions.map((qq: any) => (
                        <li key={qq.question} className="px-3 py-2 text-[12.5px]">
                          <div className="flex items-center justify-between gap-2"><span className="font-medium">{qq.question}</span><StatusBadge status={qq.answer === "Yes" ? "PASS" : qq.answer === "No" ? "FAIL" : "INSUFFICIENT_EVIDENCE"} /></div>
                          <div className="text-muted">{qq.basis}{qq.evidence ? ` · ${qq.evidence}` : ""}</div>
                        </li>
                      ))}
                    </ul>
                    <p className="text-[12px] text-muted">Control status is now <b>{title(test.control_status)}</b>. The test was recorded in the audit trail.</p>
                  </div>
                )}
              </DialogContent>
            </Dialog>
          </>
        );
      }}
    </QueryView>
  );
}

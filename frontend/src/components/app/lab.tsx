/** Shared result views for P4–P5 features — used by their pages and by the agent's result cards. */
import { Link } from "react-router";
import { ArrowRight, GitBranch, Sparkles, Sun } from "lucide-react";
import { DataTable, KV, RiskBadge, StatusBadge } from "@/components/app";
import { Badge } from "@/components/ui/badge";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { cn } from "@/lib/utils";

export function BeforeAfter({ label, before, after, suffix = "", render }: {
  label: string; before: any; after: any; suffix?: string; render?: (v: any) => React.ReactNode;
}) {
  const changed = before !== after;
  return (
    <div className="rounded-lg bg-surface-2 px-3 py-2.5">
      <div className="text-[11.5px] text-muted">{label}</div>
      <div className="mt-1 flex flex-wrap items-center gap-2 text-[15px] font-semibold tabular">
        <span className={cn(changed && "text-muted")}>{render ? render(before) : `${before}${suffix}`}</span>
        <ArrowRight className="h-3.5 w-3.5 text-subtle" />
        <span>{render ? render(after) : `${after}${suffix}`}</span>
      </div>
    </div>
  );
}

export function SimLabel({ text = "Simulation — nothing is saved" }: { text?: string }) {
  return <Badge tone="accent" className="normal-case tracking-normal">{text}</Badge>;
}

export function ControlSimResult({ r }: { r: any }) {
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2 text-[13px]">
        <SimLabel /><span className="text-muted">Scenario:</span><b>{r.changes.join(" · ") || "no change"}</b>
      </div>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <BeforeAfter label="Control status" before={r.status.before} after={r.status.after} render={(v) => <StatusBadge status={v} />} />
        <BeforeAfter label="Risk" before={r.risk.before} after={r.risk.after} render={(v) => <RiskBadge risk={v.category} score={v.score} />} />
        <BeforeAfter label={`Readiness · ${r.readiness.audit ?? "scope"}`} before={r.readiness.before} after={r.readiness.after} suffix="%" />
        <BeforeAfter label="Potential gaps" before={r.gaps.before} after={r.gaps.after} />
      </div>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card><CardHeader title={`Affected requirements · ${r.affected_requirements.length}`} /><CardBody className="space-y-1.5">
          {r.affected_requirements.length ? r.affected_requirements.map((q: any) => (
            <div key={q.code} className="flex items-center justify-between gap-2 text-[13px]"><span><span className="font-mono text-[12px] text-muted">{q.code}</span> {q.title}</span><Badge tone="neutral">{q.framework}</Badge></div>
          )) : <p className="text-[13px] text-muted">No mapped requirements.</p>}
        </CardBody></Card>
        <Card><CardHeader title="Potential finding & required approval" /><CardBody>
          {r.potential_finding ? (
            <KV items={[
              ["Finding", r.potential_finding.title], ["Severity", <RiskBadge risk={r.potential_finding.severity} />],
              ["Recurrence", r.potential_finding.would_recur ? <Badge tone="danger">Would be a recurring finding</Badge> : "First occurrence"],
              ["Required approval", r.required_approval ? <span><RiskBadge risk={r.required_approval.risk_level} /> <span className="font-mono text-[12px]">{r.required_approval.required_permission}</span></span> : "—"],
              ["For action", r.required_approval?.action ?? "—"],
            ]} />
          ) : <p className="text-[13px] text-muted">Control appears satisfied under this scenario — no finding would be raised.</p>}
        </CardBody></Card>
      </div>
      {!!r.recommended_remediation.length && (
        <Card><CardHeader title="Recommended remediation" description="The playbook the agent would generate" /><CardBody>
          <ol className="space-y-1.5 text-[13px]">{r.recommended_remediation.map((s: any) => <li key={s.seq} className="flex items-center gap-3"><span className="w-4 text-muted tabular">{s.seq}</span><span className="flex-1">{s.title}</span><RiskBadge risk={s.risk} /></li>)}</ol>
        </CardBody></Card>
      )}
    </div>
  );
}

export function PolicySimResult({ r }: { r: any }) {
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2"><SimLabel /><span className="text-[15px] font-semibold">{r.summary}</span></div>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <div className="rounded-lg bg-surface-2 px-3 py-2.5"><div className="text-[11.5px] text-muted">Affected controls</div><div className="text-[22px] font-semibold tabular">{r.affected_controls.length}</div></div>
        <div className="rounded-lg bg-surface-2 px-3 py-2.5"><div className="text-[11.5px] text-muted">Immediately overdue</div><div className="text-[22px] font-semibold tabular text-danger">{r.potential_overdue}</div></div>
        <div className="rounded-lg bg-surface-2 px-3 py-2.5"><div className="text-[11.5px] text-muted">Extra tests / year</div><div className="text-[22px] font-semibold tabular">+{r.testing_impact.extra_tests_per_year}</div></div>
        <BeforeAfter label="Audit readiness" before={r.readiness.before} after={r.readiness.after} suffix="%" />
      </div>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_280px]">
        <DataTable dense rows={r.affected_controls} rowKey={(x: any) => x.code} columns={[
          { key: "c", header: "Control", cell: (x: any) => <Link to={`/controls/${x.id}`} className="font-mono text-[12px] text-accent hover:underline">{x.code}</Link> },
          { key: "n", header: "Name", cell: (x: any) => x.name },
          { key: "i", header: "Interval", cell: (x: any) => <span className="whitespace-nowrap tabular">{x.current_interval_days}d → {r.proposed_interval_days}d</span> },
          { key: "d", header: "Last test", hideOnMobile: true, cell: (x: any) => x.days_since_test != null ? `${x.days_since_test}d ago` : "never" },
          { key: "s", header: "Status", cell: (x: any) => <span className="flex items-center gap-1"><StatusBadge status={x.status_before} />{x.status_before !== x.status_after && <><ArrowRight className="h-3 w-3 text-subtle" /><StatusBadge status={x.status_after} /></>}</span> },
          { key: "r", header: "Risk", cell: (x: any) => <span className="flex items-center gap-1"><RiskBadge risk={x.risk_before} />{x.risk_before !== x.risk_after && <><ArrowRight className="h-3 w-3 text-subtle" /><RiskBadge risk={x.risk_after} /></>}</span> },
        ]} />
        <div className="space-y-4">
          <Card><CardHeader title="Departments" /><CardBody className="space-y-1">{r.affected_departments.map((d: any) => <div key={d.name} className="flex justify-between text-[13px]"><span>{d.name}</span><b className="tabular">{d.controls}</b></div>)}</CardBody></Card>
          <Card><CardHeader title="Evidence impact" description={`${r.evidence_impact.stale_items} items older than ${r.proposed_interval_days} days`} /><CardBody className="space-y-1">
            {r.evidence_impact.items.slice(0, 6).map((e: any) => <div key={e.code} className="text-[12px]"><span className="font-mono text-muted">{e.code}</span> {e.control} · {e.age_days}d old</div>)}
          </CardBody></Card>
        </div>
      </div>
    </div>
  );
}

export function BriefView({ b, compact }: { b: any; compact?: boolean }) {
  const active = b.items.filter((i: any) => i.count);
  return (
    <div className={cn("rounded-card border border-accent/25 bg-accent-soft/50", compact ? "p-4" : "p-5")}>
      <div className="flex flex-wrap items-center gap-2">
        <Sun className="h-4 w-4 text-accent" />
        <span className="text-[11.5px] font-semibold uppercase tracking-wider text-accent">Morning Compliance Brief</span>
        <span className="text-[11.5px] text-muted">· {b.scope}</span>
      </div>
      <div className="mt-2 text-[14px]"><b>{greeting()}</b> Compliance Agent identified:</div>
      <div className="mt-2 flex flex-wrap gap-2">
        {active.length ? active.map((i: any) => (
          <Link key={i.key} to={i.link} className="rounded-lg border border-border bg-surface px-3 py-1.5 text-[12.5px] hover:border-accent/50">
            <b className="tabular">{i.count}</b> {i.label}
          </Link>
        )) : <span className="text-[13px] text-muted">Nothing needs your attention today.</span>}
      </div>
      {b.top_priority && (
        <div className="mt-3 flex flex-wrap items-center gap-2 text-[13px]">
          <span className="text-muted">Top priority:</span>
          <Link to={`/controls/${b.top_priority.id}`} className="font-semibold hover:underline">{b.top_priority.name} ({b.top_priority.code})</Link>
          <RiskBadge risk={b.top_priority.risk} /><span className="text-[12px] text-muted">{b.top_priority.why}</span>
          <Link to={`/agent?q=${encodeURIComponent(`Investigate ${b.top_priority.code}`)}`} className="ml-auto inline-flex items-center gap-1 text-[12.5px] font-medium text-accent hover:underline"><Sparkles className="h-3.5 w-3.5" />Review risks</Link>
        </div>
      )}
    </div>
  );
}

export function greeting() {
  const h = new Date().getHours();
  return `Good ${h < 12 ? "morning" : h < 17 ? "afternoon" : "evening"}.`;
}

export function DriftList({ items }: { items: any[] }) {
  if (!items.length) return <p className="text-[13px] text-muted">No potential control drift detected.</p>;
  return (
    <div className="space-y-3">
      {items.map((d) => (
        <Card key={d.control.code} className="p-4">
          <div className="flex flex-wrap items-center gap-2">
            <GitBranch className="h-4 w-4 text-warning" />
            <Link to={`/controls/${d.control.id}`} className="text-[14px] font-semibold hover:underline"><span className="font-mono text-muted">{d.control.code}</span> {d.control.name}</Link>
            <Badge tone="warning">{d.label}</Badge><StatusBadge status={d.control.status} /><RiskBadge risk={d.severity} />
          </div>
          <div className="mt-3 overflow-x-auto scrollbar-thin">
            <table className="w-full text-[12.5px]">
              <thead className="text-[11px] uppercase tracking-wider text-muted"><tr><th className="py-1 pr-3 text-left">Signal</th><th className="pr-3 text-left">Previous state</th><th className="pr-3 text-left">Current state</th><th className="text-left">Impact</th></tr></thead>
              <tbody className="divide-y divide-border">{d.signals.map((s: any, i: number) => (
                <tr key={i}><td className="py-1.5 pr-3 font-medium">{s.type}</td><td className="pr-3 text-muted">{s.previous}</td><td className="pr-3">{s.current}</td><td className="text-muted">{s.impact}</td></tr>
              ))}</tbody>
            </table>
          </div>
          {!!d.evidence.length && <div className="mt-2 flex flex-wrap gap-1.5 text-[11.5px]"><span className="text-muted">Evidence:</span>{d.evidence.map((e: any) => <Badge key={e.code} tone="neutral">{e.code} · {e.status}</Badge>)}</div>}
        </Card>
      ))}
    </div>
  );
}

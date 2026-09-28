import * as React from "react";
import { Link, useNavigate } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, CircleDashed, FileText, HelpCircle, Inbox, Loader2, Lock, ShieldAlert, XCircle } from "lucide-react";
import { Badge, type Tone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog, DialogContent, DialogTrigger } from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/misc";
import { api, ApiError } from "@/lib/api";
import { cn, fmtDateTime, title } from "@/lib/utils";

// ------------------------------------------------------------------ badges
const STATUS_TONE: Record<string, Tone> = {
  PASS: "success", VALID: "success", PASSED: "success", CLOSED: "success", COMPLETED: "success", EXECUTED: "success", APPROVED: "success", RESOLVED: "success", FRESH: "success", IMPLEMENTED: "success", ACTIVE: "success", verified: "success",
  PARTIAL: "warning", EXPIRING: "warning", AT_RISK: "warning", IN_REMEDIATION: "info", IN_PROGRESS: "info", PENDING: "neutral", AGING: "neutral", UNVERIFIED: "warning", unverified: "warning",
  PENDING_APPROVAL: "warning", AWAITING_APPROVAL: "warning", READY_FOR_CLOSURE: "accent", VERIFYING: "accent", INVESTIGATING: "warning", OPEN: "danger", REVIEW_DUE: "warning",
  FAIL: "danger", FAILED: "danger", OVERDUE: "danger", EXPIRED: "danger", MISSING: "danger", CONFLICTING: "danger", REJECTED: "danger", BLOCKED: "danger",
  CHANGE_REQUIRED: "danger", NOT_TESTED: "neutral", INSUFFICIENT_EVIDENCE: "warning", INCONCLUSIVE: "warning", CHANGES_REQUESTED: "warning",
  NEW: "accent", CHANGED: "info", RECURRING: "danger", EFFECTIVE_SOON: "warning", IMPACT_ASSESSMENT_REQUIRED: "danger", UNDER_REVIEW: "info",
  PARTIALLY_EXPIRED: "warning", DEMO: "accent", CONNECTED: "success", UNAVAILABLE: "neutral", REQUIRES_CONFIGURATION: "neutral",
};
export function StatusBadge({ status, className }: { status?: string | null; className?: string }) {
  if (!status) return <span className="text-subtle">—</span>;
  return <Badge tone={STATUS_TONE[status] ?? "neutral"} className={className}>{title(status)}</Badge>;
}
const RISK_TONE: Record<string, Tone> = { LOW: "success", MEDIUM: "warning", HIGH: "danger", CRITICAL: "critical" };
export function RiskBadge({ risk, score, className }: { risk?: string | null; score?: number | null; className?: string }) {
  if (!risk) return <span className="text-subtle">—</span>;
  return (
    <Badge tone={RISK_TONE[risk] ?? "neutral"} dot className={className}>
      {risk}{score != null && <span className="font-mono font-medium opacity-80 tabular">{Math.round(score)}</span>}
    </Badge>
  );
}

// ------------------------------------------------------------------ layout helpers
export function PageHeader({ title: t, description, actions, eyebrow }: { title: React.ReactNode; description?: React.ReactNode; actions?: React.ReactNode; eyebrow?: React.ReactNode }) {
  return (
    <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <div className="min-w-0">
        {eyebrow && <div className="mb-1 text-[11.5px] font-semibold uppercase tracking-wider text-accent">{eyebrow}</div>}
        <h1 className="text-[22px] font-semibold tracking-tight text-foreground">{t}</h1>
        {description && <p className="mt-1 max-w-3xl text-[13.5px] text-muted">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function MetricCard({ label, value, hint, tone = "neutral", icon, to, delta }: {
  label: string; value: React.ReactNode; hint?: React.ReactNode; tone?: "neutral" | "danger" | "warning" | "success" | "info"; icon?: React.ReactNode; to?: string; delta?: React.ReactNode;
}) {
  const bar = { neutral: "bg-border-strong", danger: "bg-danger", warning: "bg-warning", success: "bg-success", info: "bg-accent" }[tone];
  const inner = (
    <Card className={cn("relative overflow-hidden p-4 h-full transition-shadow", to && "hover:shadow-pop cursor-pointer")}>
      <span className={cn("absolute left-0 top-0 h-full w-[3px]", bar)} aria-hidden />
      <div className="flex items-center justify-between text-[12px] font-medium text-muted">
        <span>{label}</span>
        <span className="text-subtle">{icon}</span>
      </div>
      <div className="mt-2 flex items-baseline gap-2">
        <span className="text-[26px] font-semibold tracking-tight tabular text-foreground">{value}</span>
        {delta}
      </div>
      {hint && <div className="mt-1 text-[12px] text-muted line-clamp-1">{hint}</div>}
    </Card>
  );
  return to ? <Link to={to} className="block">{inner}</Link> : inner;
}

// ------------------------------------------------------------------ states
export function LoadingState({ label = "Loading compliance context…", rows = 4 }: { label?: string; rows?: number }) {
  return (
    <div className="space-y-3" role="status" aria-live="polite">
      <div className="flex items-center gap-2 text-[13px] text-muted"><Loader2 className="h-4 w-4 animate-spin" />{label}</div>
      {Array.from({ length: rows }).map((_, i) => <Skeleton key={i} className="h-12 w-full" />)}
    </div>
  );
}
export function EmptyState({ title: t, description, icon, action }: { title: string; description?: string; icon?: React.ReactNode; action?: React.ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center rounded-card border border-dashed border-border-strong px-6 py-12 text-center">
      <div className="mb-3 rounded-full bg-surface-2 p-3 text-muted">{icon ?? <Inbox className="h-5 w-5" />}</div>
      <div className="text-[14px] font-semibold">{t}</div>
      {description && <p className="mt-1 max-w-sm text-[13px] text-muted">{description}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}
const ERROR_TITLES: Record<string, string> = {
  NETWORK: "Can't reach the API", OFFLINE: "You're offline", TIMEOUT: "The API took too long to respond",
  MISCONFIGURED: "API URL is misconfigured", BACKEND_UNAVAILABLE: "Backend unavailable", SERVICE_UNAVAILABLE: "Database unavailable",
  UNAUTHENTICATED: "Session expired", INVALID_INPUT: "Some fields are invalid", NOT_FOUND: "Not found", RATE_LIMITED: "Slow down",
};
export function ErrorState({ error, retry }: { error: unknown; retry?: () => void }) {
  const e = error as ApiError;
  if (e?.status === 403) return <DeniedState why={e.why} />;
  const heading = ERROR_TITLES[e?.code] ?? (e?.status === 0 ? "Can't reach the API" : "The request could not be completed");
  return (
    <div className="rounded-card border border-danger/30 bg-danger-soft px-5 py-4 text-[13px] text-danger flex items-start gap-3">
      <XCircle className="h-4 w-4 mt-0.5 shrink-0" />
      <div className="flex-1">
        <div className="font-semibold">{heading}</div>
        <div className="mt-0.5 opacity-90">{e?.message ?? "Something went wrong."}</div>
        {e?.code && <div className="mt-1 font-mono text-[11px] opacity-70">{e.code}{e.status ? ` · HTTP ${e.status}` : ""}</div>}
      </div>
      {retry && <Button size="sm" onClick={retry}>Retry</Button>}
    </div>
  );
}
export function DeniedState({ why }: { why?: ApiError["why"] }) {
  return (
    <Card className="p-5">
      <div className="flex items-start gap-3">
        <div className="rounded-lg bg-danger-soft p-2 text-danger"><Lock className="h-4 w-4" /></div>
        <div className="text-[13px]">
          <div className="text-[14px] font-semibold">You don't have access to this resource.</div>
          <div className="mt-3 text-[12px] font-semibold uppercase tracking-wider text-subtle">Why was I denied?</div>
          <dl className="mt-2 grid grid-cols-[150px_1fr] gap-y-1.5">
            <dt className="text-muted">Your current role</dt><dd className="font-medium">{why?.your_role ?? "—"}</dd>
            <dt className="text-muted">Required permission</dt><dd className="font-mono text-[12px]">{why?.required_permission ?? "—"}</dd>
            <dt className="text-muted">Your permissions</dt><dd>Do not include this permission.</dd>
            <dt className="text-muted">Recommended action</dt><dd>{why?.recommended_action ?? "Request access from your Compliance Administrator."}</dd>
          </dl>
        </div>
      </div>
    </Card>
  );
}

export function QueryView<T>({ q, children, empty }: { q: { data?: T; isLoading: boolean; error: unknown; refetch: () => void }; children: (d: T) => React.ReactNode; empty?: React.ReactNode }) {
  if (q.isLoading) return <LoadingState />;
  if (q.error) return <ErrorState error={q.error} retry={q.refetch} />;
  if (q.data === undefined || (Array.isArray(q.data) && q.data.length === 0 && empty)) return <>{empty}</>;
  return <>{children(q.data)}</>;
}

// ------------------------------------------------------------------ table
export interface Column<T> { key: string; header: React.ReactNode; cell: (row: T) => React.ReactNode; className?: string; hideOnMobile?: boolean }
export function DataTable<T>({ rows, columns, onRowClick, empty, rowKey, dense }: {
  rows: T[]; columns: Column<T>[]; onRowClick?: (r: T) => void; empty?: React.ReactNode; rowKey: (r: T) => string | number; dense?: boolean;
}) {
  if (!rows.length) return <>{empty ?? <EmptyState title="Nothing to show" />}</>;
  return (
    <div className="overflow-x-auto scrollbar-thin rounded-card border border-border bg-surface">
      <table className="w-full text-left text-[13px]">
        <thead className="bg-surface-2 text-[11.5px] uppercase tracking-wider text-muted">
          <tr>{columns.map((c) => <th key={c.key} scope="col" className={cn("px-3.5 py-2.5 font-semibold whitespace-nowrap", c.hideOnMobile && "hidden md:table-cell", c.className)}>{c.header}</th>)}</tr>
        </thead>
        <tbody className="divide-y divide-border">
          {rows.map((r) => (
            <tr key={rowKey(r)} onClick={onRowClick ? () => onRowClick(r) : undefined}
              onKeyDown={onRowClick ? (e) => { if (e.key === "Enter") onRowClick(r); } : undefined}
              tabIndex={onRowClick ? 0 : undefined}
              className={cn("transition-colors", onRowClick && "cursor-pointer hover:bg-surface-2 focus:bg-surface-2")}>
              {columns.map((c) => <td key={c.key} className={cn("px-3.5 align-middle", dense ? "py-2" : "py-2.5", c.hideOnMobile && "hidden md:table-cell", c.className)}>{c.cell(r)}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ------------------------------------------------------------------ Why?
type Explain = { title: string; points: { label: string; text: string }[]; evidence: { code: string; name: string; status: string; id: number }[]; label?: string; sources?: any[] };
export function WhyButton({ kind, code, label = "Why?" }: { kind: "control" | "evidence"; code: string; label?: string }) {
  const [open, setOpen] = React.useState(false);
  const q = useQuery({ queryKey: ["explain", kind, code], queryFn: () => api.get<Explain>(`/api/explain?kind=${kind}&code=${code}`), enabled: open });
  const nav = useNavigate();
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="sm" variant="secondary" className="text-accent"><HelpCircle className="h-3.5 w-3.5" />{label}</Button>
      </DialogTrigger>
      <DialogContent title={q.data?.title ?? `Why? — ${code}`} description={q.data?.label ?? "Explanation from rules, evidence and history"}>
        <QueryView q={q}>
          {(d) => (
            <div className="space-y-4">
              <ul className="space-y-2.5">
                {d.points.map((p, i) => (
                  <li key={i} className="flex gap-3 text-[13px]">
                    <span className="mt-0.5 w-[88px] shrink-0 text-[11px] font-semibold uppercase tracking-wider text-subtle">{p.label}</span>
                    <span className="text-foreground">{p.text}</span>
                  </li>
                ))}
              </ul>
              {!!d.evidence?.length && (
                <div>
                  <div className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-subtle">Evidence</div>
                  <div className="space-y-1.5">
                    {d.evidence.map((e) => (
                      <button key={e.code} onClick={() => { setOpen(false); nav(`/evidence?focus=${e.id}`); }} className="flex w-full items-center justify-between rounded-lg border border-border px-3 py-2 text-left text-[13px] hover:bg-surface-2 cursor-pointer">
                        <span className="flex items-center gap-2"><FileText className="h-3.5 w-3.5 text-muted" /><span className="font-mono text-[12px] text-muted">{e.code}</span>{e.name}</span>
                        <StatusBadge status={e.status} />
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </QueryView>
      </DialogContent>
    </Dialog>
  );
}

// ------------------------------------------------------------------ citations & timeline
export function SourceCitation({ c }: { c: { document_id: number; document_name: string; page: number; section?: string; classification: string; version?: string; effective_date?: string | null; content?: string; matched_by?: string[] } }) {
  return (
    <Link to={`/documents/${c.document_id}`} className="block rounded-lg border border-border bg-surface px-3 py-2.5 transition-colors hover:border-accent/50 hover:bg-accent-soft/40">
      <div className="flex items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2 text-[12.5px] font-medium">
          <FileText className="h-3.5 w-3.5 shrink-0 text-accent" />
          <span className="truncate">{c.document_name.replace(/\.txt$/, "")}</span>
        </div>
        <span className="shrink-0 text-[11px] text-muted">p.{c.page}{c.version ? ` · v${c.version}` : ""}</span>
      </div>
      {c.section && <div className="mt-0.5 text-[11.5px] text-muted">§ {c.section}</div>}
      {c.content && <p className="mt-1.5 line-clamp-2 text-[12px] text-muted">“{c.content}”</p>}
      <div className="mt-1.5 flex gap-1.5"><Badge tone="neutral">{c.classification}</Badge>{c.matched_by?.map((m) => <Badge key={m} tone="accent">{m}</Badge>)}</div>
    </Link>
  );
}

const EVENT_ICON: Record<string, React.ReactNode> = {
  finding_created: <AlertTriangle className="h-3.5 w-3.5 text-danger" />, verification_failed: <XCircle className="h-3.5 w-3.5 text-danger" />,
  verification_passed: <CheckCircle2 className="h-3.5 w-3.5 text-success" />, finding_closed: <CheckCircle2 className="h-3.5 w-3.5 text-success" />,
  requirement_updated: <ShieldAlert className="h-3.5 w-3.5 text-accent" />,
};
export function Timeline({ items }: { items: { title: string; at: string | null; type?: string; actor_type?: string }[] }) {
  if (!items.length) return <EmptyState title="No events yet" />;
  return (
    <ol className="relative space-y-3 border-l border-border pl-5">
      {items.map((e, i) => (
        <li key={i} className="relative">
          <span className="absolute -left-[27px] top-0.5 flex h-4 w-4 items-center justify-center rounded-full bg-surface ring-2 ring-surface">
            {EVENT_ICON[e.type ?? ""] ?? <CircleDashed className="h-3.5 w-3.5 text-subtle" />}
          </span>
          <div className="text-[13px] text-foreground">{e.title}</div>
          <div className="text-[11.5px] text-muted">{fmtDateTime(e.at)}{e.actor_type === "agent" ? " · Compliance Agent" : e.actor_type === "system" ? " · system" : ""}</div>
        </li>
      ))}
    </ol>
  );
}

export function KV({ items, className }: { items: [React.ReactNode, React.ReactNode][]; className?: string }) {
  return (
    <dl className={cn("grid grid-cols-[minmax(110px,40%)_1fr] gap-x-3 gap-y-2 text-[13px]", className)}>
      {items.map(([k, v], i) => (<React.Fragment key={i}><dt className="text-muted">{k}</dt><dd className="min-w-0 text-foreground">{v}</dd></React.Fragment>))}
    </dl>
  );
}

export function DemoLabel({ children = "Demo Simulation" }: { children?: React.ReactNode }) {
  return <Badge tone="accent" className="normal-case tracking-normal">{children}</Badge>;
}

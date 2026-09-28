import * as React from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { Command } from "cmdk";
import {
  Activity, AlertTriangle, Bell, BookOpen, Brain, Briefcase, ClipboardCheck, FileBarChart, FileCheck2, FileText, FlaskConical, GitBranch,
  LayoutDashboard, ListChecks, LogOut, Menu as MenuIcon, Moon, Network, Radar, Scale, ScrollText, Search, Settings, ShieldAlert,
  ShieldCheck, SlidersHorizontal, Sparkles, Sun, Target, TrendingUp, UserCog, Wrench, X,
} from "lucide-react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Menu, MenuContent, MenuItem, MenuLabel, MenuSeparator, MenuTrigger } from "@/components/ui/misc";
import { useAuth, useTheme } from "@/hooks/useAuth";
import { api } from "@/lib/api";
import { cn, fmtDateTime, withViewTransition } from "@/lib/utils";

type Counts = { findings: number; evidence: number; remediation: number; approvals: number; security: number; notifications: number; controls: number };
type NavItem = { to: string; label: string; icon: React.ElementType; perms: string[]; badge?: keyof Counts; tone?: string; roles?: string[]; section?: string };
const NAV: NavItem[] = [
  { to: "/", label: "Command Center", icon: LayoutDashboard, perms: ["DASHBOARD_READ"], roles: ["COMPLIANCE_OFFICER", "AUDITOR", "SECURITY_ADMIN"] },
  { to: "/command-center", label: "Command Center", icon: LayoutDashboard, perms: ["DASHBOARD_READ"], roles: ["EXECUTIVE", "CONTROL_OWNER"] },
  { to: "/executive", label: "Executive View", icon: TrendingUp, perms: ["DASHBOARD_READ"], roles: ["EXECUTIVE", "COMPLIANCE_OFFICER"] },
  { to: "/my-work", label: "My Work", icon: Briefcase, perms: ["TASKS_READ_ASSIGNED"] },
  { to: "/agent", label: "AI Compliance Agent", icon: Sparkles, perms: ["AGENT_USE"] },
  { to: "/readiness", label: "Audit Readiness", icon: Target, perms: ["AUDITS_READ"] },
  { to: "/controls", label: "Controls", icon: ShieldCheck, perms: ["CONTROLS_READ", "CONTROLS_READ_ASSIGNED"], badge: "controls", tone: "danger" },
  { to: "/evidence", label: "Evidence", icon: FileCheck2, perms: ["EVIDENCE_READ"], badge: "evidence", tone: "warning" },
  { to: "/findings", label: "Findings", icon: AlertTriangle, perms: ["FINDINGS_READ"], badge: "findings", tone: "danger" },
  { to: "/remediation", label: "Remediation", icon: Wrench, perms: ["REMEDIATION_READ", "TASKS_READ_ASSIGNED"], badge: "approvals", tone: "warning" },
  { to: "/requirements", label: "Requirements", icon: ListChecks, perms: ["REQUIREMENTS_READ"], section: "Knowledge" },
  { to: "/policies", label: "Policies", icon: BookOpen, perms: ["POLICIES_READ"] },
  { to: "/audits", label: "Audits", icon: ClipboardCheck, perms: ["AUDITS_READ"] },
  { to: "/regulatory-changes", label: "Regulatory Changes", icon: Scale, perms: ["REQUIREMENTS_READ"] },
  { to: "/memory", label: "Agent Memory", icon: Brain, perms: ["MEMORY_READ"] },
  { to: "/reports", label: "Reports", icon: FileBarChart, perms: ["REPORTS_GENERATE", "AUDITS_READ"] },
  { to: "/policy-lab", label: "Policy Lab", icon: SlidersHorizontal, perms: ["POLICIES_MANAGE"], section: "Intelligence Lab" },
  { to: "/simulator", label: "Compliance Simulator", icon: FlaskConical, perms: ["AUDIT_RUN"] },
  { to: "/graph", label: "Compliance Graph", icon: Network, perms: ["CONTROLS_READ"] },
  { to: "/drift", label: "Control Drift", icon: GitBranch, perms: ["CONTROLS_READ"] },
  { to: "/documents", label: "Documents", icon: FileText, perms: ["DOCUMENTS_READ", "POLICIES_READ"] },
  { to: "/scans", label: "Scheduled Scans", icon: Radar, perms: ["AUDITS_READ"], section: "Operations" },
  { to: "/observability", label: "Observability", icon: Activity, perms: ["SETTINGS_MANAGE", "COMPLIANCE_READ_ALL"] },
  { to: "/security", label: "Security Center", icon: ShieldAlert, perms: ["SECURITY_EVENTS_READ"], badge: "security", tone: "danger" },
  { to: "/audit-logs", label: "Audit Logs", icon: ScrollText, perms: ["AUDIT_LOGS_READ"] },
  { to: "/settings", label: "Settings", icon: Settings, perms: [] },
];

export function useNavCounts() {
  return useQuery({ queryKey: ["nav-counts"], queryFn: () => api.get<Counts>("/api/nav-counts"), refetchInterval: 15000 });
}

function Logo() {
  return (
    <div className="flex items-center gap-2.5">
      <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary text-primary-foreground dark:bg-accent">
        <svg viewBox="0 0 24 24" className="h-4.5 w-4.5" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round"><path d="M6 18V6l12 12V6" /></svg>
      </div>
      <div className="leading-tight">
        <div className="text-[13.5px] font-semibold text-foreground">NovaTech</div>
        <div className="text-[11px] text-muted">Compliance Intelligence</div>
      </div>
    </div>
  );
}

function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const { user, can } = useAuth();
  const counts = useNavCounts().data;
  const items = NAV.filter((n) => (!n.perms.length || n.perms.some(can)) && (!n.roles || n.roles.includes(user?.role ?? "")));
  return (
    <div className="flex h-full flex-col">
      <div className="px-4 py-4"><Logo /></div>
      <nav className="flex-1 overflow-y-auto scrollbar-thin px-2.5 pb-3" aria-label="Main">
        {items.map((n) => {
          const c = n.badge && counts ? counts[n.badge] : 0;
          return (
            <React.Fragment key={n.to}>
            {n.section && <div className="mb-1 mt-4 px-2.5 text-[10.5px] font-semibold uppercase tracking-wider text-subtle">{n.section}</div>}
            <NavLink to={n.to} end={n.to === "/"} onClick={onNavigate}
              className={({ isActive }) => cn("group mb-0.5 flex items-center gap-2.5 rounded-lg px-2.5 py-[7px] text-[13px] font-medium transition-colors",
                isActive ? "bg-primary-soft text-foreground dark:bg-surface-2" : "text-muted hover:bg-surface-2 hover:text-foreground")}>
              {({ isActive }) => (<>
                <n.icon className={cn("h-4 w-4 shrink-0", isActive ? "text-accent" : "text-subtle group-hover:text-muted")} />
                <span className="flex-1 truncate">{n.label}</span>
                {!!c && <span className={cn("min-w-5 rounded-full px-1.5 text-center text-[10.5px] font-semibold tabular leading-[18px]",
                  n.tone === "danger" ? "bg-danger-soft text-danger" : "bg-warning-soft text-warning")}>{c}</span>}
              </>)}
            </NavLink>
            </React.Fragment>
          );
        })}
      </nav>
      {user && (
        <div className="border-t border-border p-3">
          <div className="flex items-center gap-2.5 rounded-lg px-1.5 py-1">
            <div className="flex h-8 w-8 items-center justify-center rounded-full bg-accent-soft text-[12px] font-semibold text-accent">
              {user.name.split(" ").map((s) => s[0]).join("").slice(0, 2)}
            </div>
            <div className="min-w-0 flex-1 leading-tight">
              <div className="truncate text-[13px] font-medium">{user.name}</div>
              <div className="truncate text-[11.5px] text-muted">{user.role_name} · {user.company.name}</div>
            </div>
          </div>
          <div className="mt-2 flex items-center justify-between rounded-md bg-accent-soft px-2 py-1 text-[11px] font-semibold text-accent">
            <span>Environment: DEMO</span><span className="font-normal opacity-80">{user.auth_method}</span>
          </div>
        </div>
      )}
    </div>
  );
}

function Personas() {
  const { user, login } = useAuth();
  const nav = useNavigate();
  const q = useQuery({ queryKey: ["personas"], queryFn: () => api.get<{ name: string; email: string; role: string; role_name: string; title: string }[]>("/api/auth/personas") });
  return (
    <Menu>
      <MenuTrigger asChild>
        <Button size="sm" variant="secondary" className="hidden sm:inline-flex"><UserCog className="h-3.5 w-3.5" />Demo Environment</Button>
      </MenuTrigger>
      <MenuContent align="end" className="w-72">
        <MenuLabel>Switch demo persona</MenuLabel>
        {q.data?.map((p) => (
          <MenuItem key={p.email} onSelect={async () => {
            await login({ mode: "demo", email: p.email });
            toast.success(`Signed in as ${p.name} (${p.role_name})`);
            nav("/");
          }}>
            <div className="flex-1">
              <div className="font-medium">{p.name}</div>
              <div className="text-[11.5px] text-muted">{p.role_name} · {p.title}</div>
            </div>
            {user?.email === p.email && <Badge tone="accent">current</Badge>}
          </MenuItem>
        ))}
        <MenuSeparator />
        <div className="px-2.5 py-1.5 text-[11px] text-muted">Demo identities — mock enterprise authentication, not a real SSO provider.</div>
      </MenuContent>
    </Menu>
  );
}

function Notifications() {
  const counts = useNavCounts();
  const nav = useNavigate();
  const q = useQuery({ queryKey: ["notifications"], queryFn: () => api.get<any[]>("/api/notifications") });
  return (
    <Menu onOpenChange={(o) => { if (o) q.refetch(); }}>
      <MenuTrigger asChild>
        <Button size="icon" variant="ghost" aria-label="Notifications" className="relative">
          <Bell className="h-4 w-4" />
          {!!counts.data?.notifications && <span className="absolute right-1.5 top-1.5 h-2 w-2 rounded-full bg-danger" />}
        </Button>
      </MenuTrigger>
      <MenuContent align="end" className="w-[360px] max-h-[70vh] overflow-y-auto scrollbar-thin">
        <div className="flex items-center justify-between px-2.5 py-1.5">
          <MenuLabel className="p-0">Notifications</MenuLabel>
          <button className="text-[11.5px] text-accent hover:underline cursor-pointer" onClick={async () => { await api.post("/api/notifications/read-all"); q.refetch(); counts.refetch(); }}>Mark all read</button>
        </div>
        {q.data?.length ? q.data.map((n) => (
          <MenuItem key={n.id} onSelect={async () => { await api.post(`/api/notifications/${n.id}/read`); counts.refetch(); if (n.link) nav(n.link); }} className="items-start">
            <span className={cn("mt-1.5 h-2 w-2 shrink-0 rounded-full", n.is_read ? "bg-transparent" : n.severity === "danger" ? "bg-danger" : n.severity === "warning" ? "bg-warning" : "bg-accent")} />
            <div className="min-w-0">
              <div className={cn("text-[13px]", !n.is_read && "font-medium")}>{n.title}</div>
              <div className="text-[11.5px] text-muted">{fmtDateTime(n.at)}{n.simulated_delivery ? " · Demo Notification" : ""}</div>
            </div>
          </MenuItem>
        )) : <div className="px-3 py-6 text-center text-[13px] text-muted">You're all caught up.</div>}
      </MenuContent>
    </Menu>
  );
}

function CommandPalette({ open, setOpen }: { open: boolean; setOpen: (b: boolean) => void }) {
  const nav = useNavigate();
  const { can, user } = useAuth();
  const go = (to: string) => { setOpen(false); nav(to); };
  const prompts = ["Prepare NovaTech for our upcoming ISO 27001-style audit.", "Why is Control C-017 considered high risk?", "Show me recurring compliance findings.", "What changed since the previous audit?"];
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-slate-950/40 p-4 pt-[12vh]" onClick={() => setOpen(false)}>
      <Command className="w-full max-w-xl overflow-hidden rounded-xl border border-border bg-surface shadow-pop nt-in" onClick={(e) => e.stopPropagation()} label="Command palette">
        <div className="flex items-center gap-2 border-b border-border px-3.5">
          <Search className="h-4 w-4 text-muted" />
          <Command.Input autoFocus placeholder="Jump to a page or ask the Compliance Agent…" className="h-12 flex-1 bg-transparent text-sm outline-none placeholder:text-subtle" />
          <kbd className="rounded border border-border px-1.5 text-[10px] text-muted">ESC</kbd>
        </div>
        <Command.List className="max-h-[50vh] overflow-y-auto p-1.5 scrollbar-thin">
          <Command.Empty className="px-3 py-6 text-center text-[13px] text-muted">No matches.</Command.Empty>
          {can("AGENT_USE") && (
            <Command.Group heading="Ask the Compliance Agent" className="[&_[cmdk-group-heading]]:px-2.5 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-[11px] [&_[cmdk-group-heading]]:font-semibold [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:text-subtle">
              {prompts.map((p) => (
                <Command.Item key={p} onSelect={() => go(`/agent?q=${encodeURIComponent(p)}`)} className="flex cursor-pointer items-center gap-2 rounded-lg px-2.5 py-2 text-[13px] data-[selected=true]:bg-surface-2">
                  <Sparkles className="h-3.5 w-3.5 text-accent" />{p}
                </Command.Item>
              ))}
            </Command.Group>
          )}
          <Command.Group heading="Navigate" className="[&_[cmdk-group-heading]]:px-2.5 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-[11px] [&_[cmdk-group-heading]]:font-semibold [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:text-subtle">
            {NAV.filter((n) => (!n.perms.length || n.perms.some(can)) && (!n.roles || n.roles.includes(user?.role ?? ""))).map((n) => (
              <Command.Item key={n.to} onSelect={() => go(n.to)} className="flex cursor-pointer items-center gap-2 rounded-lg px-2.5 py-2 text-[13px] data-[selected=true]:bg-surface-2">
                <n.icon className="h-3.5 w-3.5 text-muted" />{n.label}
              </Command.Item>
            ))}
          </Command.Group>
        </Command.List>
      </Command>
    </div>
  );
}

export default function AppShell() {
  const { logout, user } = useAuth();
  const { dark, toggle } = useTheme();
  const [mobile, setMobile] = React.useState(false);
  const [palette, setPalette] = React.useState(false);
  const loc = useLocation();
  React.useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setPalette((v) => !v); }
      if (e.key === "Escape") setPalette(false);
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, []);
  React.useEffect(() => setMobile(false), [loc.pathname]);
  const wide = loc.pathname.startsWith("/agent");
  return (
    <div className="flex min-h-screen">
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-surface focus:px-3 focus:py-2">Skip to content</a>
      <aside className="sticky top-0 hidden h-screen w-[248px] shrink-0 border-r border-border bg-surface lg:block"><Sidebar /></aside>
      {mobile && (
        <div className="fixed inset-0 z-40 lg:hidden" role="dialog" aria-modal>
          <div className="absolute inset-0 bg-slate-950/40" onClick={() => setMobile(false)} />
          <aside className="absolute left-0 top-0 h-full w-[264px] border-r border-border bg-surface nt-in">
            <button className="absolute right-2 top-3 rounded p-1 text-muted cursor-pointer" onClick={() => setMobile(false)} aria-label="Close menu"><X className="h-4 w-4" /></button>
            <Sidebar onNavigate={() => setMobile(false)} />
          </aside>
        </div>
      )}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-14 items-center gap-2 border-b border-border bg-surface/85 px-4 backdrop-blur supports-[backdrop-filter]:bg-surface/70 sm:px-6">
          <Button size="icon" variant="ghost" className="lg:hidden" onClick={() => setMobile(true)} aria-label="Open menu"><MenuIcon className="h-4 w-4" /></Button>
          <button onClick={() => setPalette(true)} className="flex h-9 max-w-sm flex-1 items-center gap-2 rounded-lg border border-border bg-surface-2 px-3 text-left text-[13px] text-subtle hover:border-border-strong cursor-pointer">
            <Search className="h-3.5 w-3.5" /><span className="flex-1 truncate">Search or ask the agent…</span>
            <kbd className="hidden rounded border border-border bg-surface px-1.5 text-[10px] sm:inline">⌘K</kbd>
          </button>
          <div className="ml-auto flex items-center gap-1.5">
            <Badge tone="accent" className="hidden md:inline-flex">Demo Mode</Badge>
            <Personas />
            <Notifications />
            <Button size="icon" variant="ghost" onClick={() => withViewTransition(toggle)} aria-label="Toggle theme">{dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}</Button>
            <Button size="icon" variant="ghost" onClick={logout} aria-label={`Sign out ${user?.name ?? ""}`}><LogOut className="h-4 w-4" /></Button>
          </div>
        </header>
        <main id="main" className={cn("mx-auto w-full flex-1 px-4 py-6 sm:px-6", wide ? "max-w-[1600px]" : "max-w-[1400px]")}>
          <Outlet />
        </main>
      </div>
      <CommandPalette open={palette} setOpen={setPalette} />
    </div>
  );
}

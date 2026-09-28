import * as React from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { ArrowRight, Building2, KeyRound, ShieldCheck } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Input, Label } from "@/components/ui/input";
import { useAuth } from "@/hooks/useAuth";
import { ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";

const ROLES = [
  { code: "COMPLIANCE_OFFICER", label: "Compliance Officer", who: "Priya Raman", hint: "Runs audits, approves high-risk actions" },
  { code: "AUDITOR", label: "Auditor", who: "Arjun Mehta", hint: "Reviews scope, evidence and lineage" },
  { code: "SECURITY_ADMIN", label: "Security Admin", who: "Kavya Nair", hint: "Security events and anomalies" },
  { code: "CONTROL_OWNER", label: "Control Owner", who: "Rahul Verma", hint: "Owns C-017, uploads evidence" },
  { code: "EMPLOYEE", label: "Employee", who: "Sneha Iyer", hint: "Assigned tasks and policies" },
  { code: "EXECUTIVE", label: "Executive", who: "Vikram Sethi", hint: "Posture, critical risks, readiness" },
];

const schema = z.object({ email: z.string().email("Enter a valid email"), password: z.string().min(6, "Password is required") });
type Form = z.infer<typeof schema>;

function LineageArt() {
  const nodes = [
    { x: 40, y: 60, l: "Requirement" }, { x: 170, y: 30, l: "Control" }, { x: 170, y: 110, l: "Policy" },
    { x: 300, y: 70, l: "Evidence" }, { x: 420, y: 30, l: "Test" }, { x: 420, y: 120, l: "Finding" }, { x: 540, y: 75, l: "Verified" },
  ];
  const edges = [[0, 1], [0, 2], [1, 3], [2, 3], [3, 4], [3, 5], [4, 6], [5, 6]];
  return (
    <svg viewBox="0 0 600 160" className="w-full max-w-[560px] opacity-90" aria-hidden>
      {edges.map(([a, b], i) => (
        <path key={i} d={`M${nodes[a].x + 44} ${nodes[a].y + 12} C ${(nodes[a].x + nodes[b].x) / 2 + 22} ${nodes[a].y + 12}, ${(nodes[a].x + nodes[b].x) / 2 + 22} ${nodes[b].y + 12}, ${nodes[b].x} ${nodes[b].y + 12}`}
          stroke="rgb(143 180 255 / .35)" strokeWidth="1.2" fill="none" />
      ))}
      {nodes.map((n, i) => (
        <g key={i}>
          <rect x={n.x} y={n.y} width="88" height="24" rx="6" fill={i === 6 ? "rgb(16 185 129 / .18)" : "rgb(255 255 255 / .06)"} stroke={i === 6 ? "rgb(52 211 153 / .6)" : "rgb(143 180 255 / .35)"} />
          <text x={n.x + 44} y={n.y + 16} textAnchor="middle" fontSize="10.5" fill={i === 6 ? "#a7f3d0" : "#c7d4f5"} fontFamily="Inter">{n.l}</text>
        </g>
      ))}
    </svg>
  );
}

export default function Login() {
  const { login } = useAuth();
  const [role, setRole] = React.useState("COMPLIANCE_OFFICER");
  const [busy, setBusy] = React.useState<string | null>(null);
  const [err, setErr] = React.useState<string | null>(null);
  const [sso, setSso] = React.useState(false);
  const { register, handleSubmit, formState: { errors } } = useForm<Form>({ defaultValues: { email: "", password: "" } });

  const run = async (key: string, fn: () => Promise<void>) => {
    setBusy(key); setErr(null);
    try { await fn(); } catch (e) { setErr((e as ApiError).message); } finally { setBusy(null); }
  };
  const onPassword = handleSubmit((v) => {
    const r = schema.safeParse(v);
    if (!r.success) { setErr(r.error.issues[0].message); return; }
    run("pw", () => login({ mode: "password", email: v.email, password: v.password }));
  });

  return (
    <div className="grid min-h-screen lg:grid-cols-[1.1fr_1fr]">
      <section className="relative hidden overflow-hidden bg-[#0b1430] p-12 text-white lg:flex lg:flex-col">
        <div className="absolute inset-0 opacity-[.07]" style={{ backgroundImage: "radial-gradient(circle at 1px 1px, #fff 1px, transparent 0)", backgroundSize: "22px 22px" }} />
        <div className="relative flex items-center gap-2.5">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-white/10 ring-1 ring-white/15">
            <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="#8fb4ff" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round"><path d="M6 18V6l12 12V6" /></svg>
          </div>
          <div className="text-[15px] font-semibold tracking-tight">NovaTech Solutions</div>
        </div>
        <div className="relative mt-auto max-w-xl">
          <div className="mb-3 text-[12px] font-semibold uppercase tracking-[.16em] text-[#8fb4ff]">Continuous Compliance Intelligence</div>
          <h1 className="text-[34px] font-semibold leading-tight tracking-tight">Compliance shouldn't begin when the auditor arrives.</h1>
          <p className="mt-4 text-[15px] leading-relaxed text-[#c7d4f5]">Turn audit history, controls and evidence into continuous compliance intelligence — an AI agent that detects gaps, investigates recurring findings, plans remediation, asks for approval, verifies outcomes and remembers what happened for the next audit.</p>
          <div className="mt-10"><LineageArt /></div>
          <div className="mt-8 flex flex-wrap gap-x-6 gap-y-2 text-[12.5px] text-[#9fb0d9]">
            <span>Understand → Detect → Investigate → Act → Verify → Remember</span>
          </div>
        </div>
      </section>

      <section className="flex items-center justify-center p-6 sm:p-10">
        <div className="w-full max-w-[420px]">
          <div className="mb-8 lg:hidden text-[15px] font-semibold">NovaTech Compliance Intelligence</div>
          <h2 className="text-[22px] font-semibold tracking-tight">Sign in</h2>
          <p className="mt-1 text-[13.5px] text-muted">AI-powered audit readiness, control monitoring and remediation.</p>

          <Button variant="primary" size="lg" className="mt-6 w-full" onClick={() => setSso(true)}>
            <Building2 className="h-4 w-4" />Sign in with Company SSO
          </Button>
          <p className="mt-1.5 text-center text-[11.5px] text-subtle">Demo SAML SSO — simulated identity provider</p>

          <div className="my-6 flex items-center gap-3 text-[11px] font-semibold uppercase tracking-wider text-subtle"><span className="h-px flex-1 bg-border" />Demo Environment<span className="h-px flex-1 bg-border" /></div>

          <fieldset>
            <legend className="mb-2 text-[12.5px] font-medium text-muted">Continue as a demo role</legend>
            <div className="grid grid-cols-2 gap-2">
              {ROLES.map((r) => (
                <button key={r.code} type="button" onClick={() => setRole(r.code)} aria-pressed={role === r.code}
                  className={cn("rounded-lg border px-3 py-2 text-left transition-colors cursor-pointer",
                    role === r.code ? "border-accent bg-accent-soft" : "border-border hover:border-border-strong bg-surface")}>
                  <div className="text-[13px] font-medium">{r.label}</div>
                  <div className="text-[11.5px] text-muted line-clamp-1">{r.who}</div>
                </button>
              ))}
            </div>
          </fieldset>
          <Button variant="accent" size="lg" className="mt-3 w-full" loading={busy === "demo"} onClick={() => run("demo", () => login({ mode: "demo", role }))}>
            Continue as Demo User <ArrowRight className="h-4 w-4" />
          </Button>
          <p className="mt-2 text-[11.5px] text-muted">{ROLES.find((r) => r.code === role)?.hint}</p>

          <details className="mt-6 rounded-lg border border-border bg-surface px-4 py-3">
            <summary className="flex cursor-pointer items-center gap-2 text-[13px] font-medium"><KeyRound className="h-3.5 w-3.5 text-muted" />Sign in with email and password</summary>
            <form onSubmit={onPassword} className="mt-3 space-y-3" noValidate>
              <div className="space-y-1"><Label htmlFor="email">Work email</Label><Input id="email" autoComplete="username" placeholder="priya.raman@novatech.demo" {...register("email")} />
                {errors.email && <p className="text-[12px] text-danger">{errors.email.message}</p>}</div>
              <div className="space-y-1"><Label htmlFor="pw">Password</Label><Input id="pw" type="password" autoComplete="current-password" {...register("password")} /></div>
              <Button type="submit" className="w-full" loading={busy === "pw"}>Sign in</Button>
              <p className="text-[11.5px] text-subtle">Demo password for all personas: <span className="font-mono">NovaTech-Demo-2026</span></p>
            </form>
          </details>
          {err && <div role="alert" className="mt-4 rounded-lg bg-danger-soft px-3 py-2 text-[13px] text-danger">{err}</div>}
          <div className="mt-8 flex items-center gap-2 text-[11.5px] text-subtle"><ShieldCheck className="h-3.5 w-3.5" />Prototype · fictional NovaTech data · no legal advice or certification.</div>
        </div>
      </section>

      <Dialog open={sso} onOpenChange={setSso}>
        <DialogContent title="Demo SAML SSO" description="Simulated identity provider for the hackathon prototype. No real SSO is contacted.">
          <div className="space-y-2">
            {ROLES.map((r) => (
              <button key={r.code} onClick={() => run("sso", () => login({ mode: "sso", role: r.code }))}
                className="flex w-full items-center justify-between rounded-lg border border-border px-3 py-2.5 text-left hover:bg-surface-2 cursor-pointer">
                <div><div className="text-[13px] font-medium">{r.who}</div><div className="text-[11.5px] text-muted">{r.label}</div></div>
                <Badge tone="accent">novatech.demo</Badge>
              </button>
            ))}
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}

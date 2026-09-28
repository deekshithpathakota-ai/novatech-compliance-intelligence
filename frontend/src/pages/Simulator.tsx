import * as React from "react";
import { useSearchParams } from "react-router";
import { useMutation, useQuery } from "@tanstack/react-query";
import { FlaskConical } from "lucide-react";
import { EmptyState, ErrorState, LoadingState, PageHeader } from "@/components/app";
import { ControlSimResult } from "@/components/app/lab";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input, Label, Select } from "@/components/ui/input";
import { api } from "@/lib/api";
import type { ControlRow } from "@/types";

export default function Simulator() {
  const [p] = useSearchParams();
  const controls = useQuery({ queryKey: ["controls", ""], queryFn: () => api.get<ControlRow[]>("/api/controls") });
  const [fw, setFw] = React.useState("");
  const [dept, setDept] = React.useState("");
  const [code, setCode] = React.useState(p.get("control") ?? "C-042");
  const [test, setTest] = React.useState("FAIL");
  const [ev, setEv] = React.useState("");
  const [freq, setFreq] = React.useState("");
  const sim = useMutation({ mutationFn: () => api.post<any>("/api/simulate/control", {
    control_code: code, test_result: test || null, evidence_state: ev || null, frequency_days: freq ? Number(freq) : null }) });
  const list = (controls.data ?? []).filter((c) => (!fw || c.frameworks.includes(fw)) && (!dept || c.department === dept));
  const depts = Array.from(new Set((controls.data ?? []).map((c) => c.department).filter(Boolean))) as string[];
  const cur = controls.data?.find((c) => c.code === code);
  return (
    <>
      <PageHeader eyebrow="Intelligence Lab" title="Compliance Simulator" description="“What happens if this control fails?” — see the affected requirements, risk change, readiness impact, the finding that would be raised, the remediation and the approval it would need." />
      <Card className="mb-5 p-4">
        <form className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-7 items-end" onSubmit={(e) => { e.preventDefault(); sim.mutate(); }}>
          <div className="space-y-1"><Label>Framework</Label><Select value={fw} onChange={(e) => setFw(e.target.value)} className="w-full"><option value="">All</option>{["ISO27001", "SOC2", "NIST_CSF", "DPDP"].map((f) => <option key={f}>{f}</option>)}</Select></div>
          <div className="space-y-1"><Label>Department</Label><Select value={dept} onChange={(e) => setDept(e.target.value)} className="w-full"><option value="">All</option>{depts.sort().map((d) => <option key={d}>{d}</option>)}</Select></div>
          <div className="col-span-2 space-y-1"><Label>Control</Label><Select value={code} onChange={(e) => setCode(e.target.value)} className="w-full">{list.map((c) => <option key={c.code} value={c.code}>{c.code} · {c.name}</option>)}</Select></div>
          <div className="space-y-1"><Label>Test result</Label><Select value={test} onChange={(e) => setTest(e.target.value)} className="w-full"><option value="">Unchanged</option><option>FAIL</option><option>PARTIAL</option><option>PASS</option></Select></div>
          <div className="space-y-1"><Label>Evidence status</Label><Select value={ev} onChange={(e) => setEv(e.target.value)} className="w-full"><option value="">Unchanged</option><option>EXPIRED</option><option>MISSING</option><option>CONFLICTING</option><option>VALID</option></Select></div>
          <div className="space-y-1"><Label>Test frequency (days)</Label><Input type="number" min={7} max={730} placeholder={cur ? String(cur.frequency_days) : ""} value={freq} onChange={(e) => setFreq(e.target.value)} /></div>
          <div className="col-span-2 md:col-span-4 xl:col-span-7 flex items-center gap-3">
            <Button type="submit" variant="primary" loading={sim.isPending}><FlaskConical className="h-4 w-4" />Simulate</Button>
            {cur && <span className="text-[12px] text-muted">Current: {cur.status.replace("_", " ").toLowerCase()} · risk {cur.risk_category} · every {cur.frequency_days} days · owner {cur.owner}</span>}
          </div>
        </form>
      </Card>
      {sim.isPending ? <LoadingState label="Simulating…" /> : sim.error ? <ErrorState error={sim.error} /> : sim.data ? <ControlSimResult r={sim.data} />
        : <EmptyState title="Pick a control and a scenario" description="Nothing is saved — simulations run in a throwaway transaction." />}
    </>
  );
}

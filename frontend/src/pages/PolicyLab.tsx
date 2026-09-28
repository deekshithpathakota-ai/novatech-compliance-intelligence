import * as React from "react";
import { useSearchParams } from "react-router";
import { useMutation, useQuery } from "@tanstack/react-query";
import { FlaskConical } from "lucide-react";
import { EmptyState, ErrorState, LoadingState, PageHeader } from "@/components/app";
import { PolicySimResult } from "@/components/app/lab";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input, Label, Select } from "@/components/ui/input";
import { api } from "@/lib/api";

const PRESETS = [30, 60, 90, 180];

export default function PolicyLab() {
  const [p, setP] = useSearchParams();
  const policies = useQuery({ queryKey: ["policies"], queryFn: () => api.get<any[]>("/api/policies") });
  const [policy, setPolicy] = React.useState(p.get("policy") ?? "POL-002");
  const [days, setDays] = React.useState(Number(p.get("days") ?? 60));
  const sim = useMutation({ mutationFn: () => api.post<any>("/api/policies/simulate-change", { policy_code: policy, proposed_interval_days: days }) });
  const ran = React.useRef(false);
  React.useEffect(() => { if (!ran.current) { ran.current = true; sim.mutate(); } }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const current = policies.data?.find((x) => x.code === policy);
  const run = () => { setP({ policy, days: String(days) }, { replace: true }); sim.mutate(); };
  return (
    <>
      <PageHeader eyebrow="Intelligence Lab" title="Policy Lab" description="Simulate a policy change before you make it: which controls, departments, evidence and tests would be affected — and what becomes overdue on day one." />
      <Card className="mb-5 p-4">
        <form className="flex flex-wrap items-end gap-3" onSubmit={(e) => { e.preventDefault(); run(); }}>
          <div className="w-full space-y-1 sm:w-auto"><Label htmlFor="pol">Policy</Label>
            <Select id="pol" value={policy} onChange={(e) => setPolicy(e.target.value)} className="w-full sm:w-auto sm:min-w-[260px]">
              {policies.data?.map((x) => <option key={x.code} value={x.code}>{x.code} · {x.name} v{x.version}</option>)}
            </Select></div>
          <div className="space-y-1"><Label htmlFor="days">Proposed review interval (days)</Label>
            <Input id="days" type="number" min={7} max={730} value={days} onChange={(e) => setDays(Number(e.target.value))} className="w-32" /></div>
          <div className="flex gap-1">{PRESETS.map((d) => <Button key={d} type="button" size="sm" variant={d === days ? "accent" : "secondary"} onClick={() => setDays(d)}>{d}d</Button>)}</div>
          <Button type="submit" variant="primary" loading={sim.isPending}><FlaskConical className="h-4 w-4" />Simulate</Button>
          {current && <span className="text-[12px] text-muted">Governs {current.controls.join(", ")} · reviewed every {current.review_frequency_days} days</span>}
        </form>
      </Card>
      {sim.isPending ? <LoadingState label="Simulating policy change…" /> : sim.error ? <ErrorState error={sim.error} /> : sim.data ? <PolicySimResult r={sim.data} /> : <EmptyState title="Choose a policy and interval" />}
    </>
  );
}

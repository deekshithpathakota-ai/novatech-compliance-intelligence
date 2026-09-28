import { useQuery } from "@tanstack/react-query";
import { PageHeader, QueryView } from "@/components/app";
import { DriftList } from "@/components/app/lab";
import { api } from "@/lib/api";

export default function Drift() {
  const q = useQuery({ queryKey: ["drift"], queryFn: () => api.get<any[]>("/api/drift") });
  return (
    <>
      <PageHeader eyebrow="Intelligence Lab" title="Control Drift" description="Controls whose current implementation no longer matches what was designed or last evidenced: changed requirements, changed policies, changed owners, changed evidence or a slipping cadence." />
      <QueryView q={q}>{(items) => <DriftList items={items} />}</QueryView>
    </>
  );
}

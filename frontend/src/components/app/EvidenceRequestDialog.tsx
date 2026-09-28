import * as React from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Send } from "lucide-react";
import { toast } from "sonner";
import { KV } from "@/components/app";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Input, Label, Textarea } from "@/components/ui/input";
import { api, ApiError } from "@/lib/api";

/** Evidence request workflow: preview recipient, control, evidence, due date and reason, then Send or Cancel. */
export function EvidenceRequestDialog({ control, onClose }: { control: { control_id: number; control_code: string; control_name: string; owner: string | null }; onClose: () => void }) {
  const qc = useQueryClient();
  const due = new Date(Date.now() + 7 * 86400000).toISOString().slice(0, 10);
  const [busy, setBusy] = React.useState(false);
  const [evidence, setEvidence] = React.useState(`Current evidence for ${control.control_name}`);
  const [reason, setReason] = React.useState("No evidence on file — required for the upcoming audit.");
  const [date, setDate] = React.useState(due);
  const send = async () => {
    setBusy(true);
    try {
      const r = await api.post<any>("/api/evidence-requests", { control_id: control.control_id, evidence_required: evidence, reason, due_date: date });
      toast.success(`${r.code} sent to ${r.recipient} — Demo Notification`);
      ["evidence-requests", "notifications", "nav-counts"].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
      onClose();
    } catch (e) { toast.error((e as ApiError).message); } finally { setBusy(false); }
  };
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent title="Request evidence from control owner" description="Sent as a Demo Notification — no real email is delivered.">
        <div className="space-y-3">
          <KV items={[["Recipient", control.owner ?? "Unassigned"], ["Control", `${control.control_code} — ${control.control_name}`], ["Delivery", <Badge tone="accent">Demo Notification</Badge>]]} />
          <div className="space-y-1"><Label htmlFor="er-ev">Evidence required</Label><Input id="er-ev" value={evidence} onChange={(e) => setEvidence(e.target.value)} /></div>
          <div className="space-y-1"><Label htmlFor="er-due">Due date</Label><Input id="er-due" type="date" value={date} onChange={(e) => setDate(e.target.value)} /></div>
          <div className="space-y-1"><Label htmlFor="er-r">Reason</Label><Textarea id="er-r" rows={2} value={reason} onChange={(e) => setReason(e.target.value)} /></div>
          <div className="flex justify-end gap-2 pt-1"><Button onClick={onClose}>Cancel</Button><Button variant="primary" loading={busy} onClick={send} disabled={!control.owner}><Send className="h-3.5 w-3.5" />Send Request</Button></div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

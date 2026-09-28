import { lazy, Suspense } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router";
import AppShell from "@/layouts/AppShell";
import { LoadingState } from "@/components/app";
import { useAuth } from "@/hooks/useAuth";
import Login from "@/pages/Login";

const CommandCenter = lazy(() => import("@/pages/CommandCenter"));
const AgentPage = lazy(() => import("@/features/agent/AgentPage"));
const Readiness = lazy(() => import("@/pages/Readiness"));
const Controls = lazy(() => import("@/pages/Controls"));
const ControlDetail = lazy(() => import("@/pages/ControlDetail"));
const Evidence = lazy(() => import("@/pages/Evidence"));
const Findings = lazy(() => import("@/pages/Findings"));
const FindingDetail = lazy(() => import("@/pages/FindingDetail"));
const Remediation = lazy(() => import("@/pages/Remediation"));
const Requirements = lazy(() => import("@/pages/Requirements"));
const Policies = lazy(() => import("@/pages/Policies"));
const Audits = lazy(() => import("@/pages/Audits"));
const AuditDetail = lazy(() => import("@/pages/AuditDetail"));
const Regulatory = lazy(() => import("@/pages/Regulatory"));
const Memory = lazy(() => import("@/pages/Memory"));
const Reports = lazy(() => import("@/pages/Reports"));
const ReportView = lazy(() => import("@/pages/ReportView"));
const Documents = lazy(() => import("@/pages/Documents"));
const DocumentView = lazy(() => import("@/pages/DocumentView"));
const Security = lazy(() => import("@/pages/Security"));
const AuditLogs = lazy(() => import("@/pages/AuditLogs"));
const SettingsPage = lazy(() => import("@/pages/Settings"));
const PolicyLab = lazy(() => import("@/pages/PolicyLab"));
const Simulator = lazy(() => import("@/pages/Simulator"));
const AuditReplay = lazy(() => import("@/pages/AuditReplay"));
const ComplianceGraph = lazy(() => import("@/pages/ComplianceGraph"));
const Drift = lazy(() => import("@/pages/Drift"));
const Scans = lazy(() => import("@/pages/Scans"));
const Observability = lazy(() => import("@/pages/Observability"));
const MyWork = lazy(() => import("@/pages/MyWork"));
const Executive = lazy(() => import("@/pages/Executive"));

function Home() {
  const { can, user } = useAuth();
  if (user?.role === "EXECUTIVE") return <Navigate to="/executive" replace />;
  if (user?.role === "CONTROL_OWNER" || user?.role === "EMPLOYEE") return <Navigate to="/my-work" replace />;
  if (can("DASHBOARD_READ")) return <CommandCenter />;
  return <Navigate to="/agent" replace />;
}

export default function App() {
  const { user, ready } = useAuth();
  if (!ready) return <div className="p-10"><LoadingState label="Restoring your session…" rows={2} /></div>;
  if (!user) return <BrowserRouter><Routes><Route path="*" element={<Login />} /></Routes></BrowserRouter>;
  return (
    <BrowserRouter>
      <Suspense fallback={<div className="p-10"><LoadingState rows={3} /></div>}>
        <Routes>
          <Route element={<AppShell />}>
            <Route index element={<Home />} />
            <Route path="agent" element={<AgentPage />} />
            <Route path="readiness" element={<Readiness />} />
            <Route path="controls" element={<Controls />} />
            <Route path="controls/:id" element={<ControlDetail />} />
            <Route path="evidence" element={<Evidence />} />
            <Route path="findings" element={<Findings />} />
            <Route path="findings/:id" element={<FindingDetail />} />
            <Route path="remediation" element={<Remediation />} />
            <Route path="requirements" element={<Requirements />} />
            <Route path="policies" element={<Policies />} />
            <Route path="audits" element={<Audits />} />
            <Route path="audits/:id" element={<AuditDetail />} />
            <Route path="regulatory-changes" element={<Regulatory />} />
            <Route path="memory" element={<Memory />} />
            <Route path="reports" element={<Reports />} />
            <Route path="reports/:id" element={<ReportView />} />
            <Route path="documents" element={<Documents />} />
            <Route path="documents/:id" element={<DocumentView />} />
            <Route path="security" element={<Security />} />
            <Route path="audit-logs" element={<AuditLogs />} />
            <Route path="settings" element={<SettingsPage />} />
            <Route path="command-center" element={<CommandCenter />} />
            <Route path="policy-lab" element={<PolicyLab />} />
            <Route path="simulator" element={<Simulator />} />
            <Route path="audits/:id/replay" element={<AuditReplay />} />
            <Route path="graph" element={<ComplianceGraph />} />
            <Route path="drift" element={<Drift />} />
            <Route path="scans" element={<Scans />} />
            <Route path="observability" element={<Observability />} />
            <Route path="my-work" element={<MyWork />} />
            <Route path="executive" element={<Executive />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </Suspense>
    </BrowserRouter>
  );
}

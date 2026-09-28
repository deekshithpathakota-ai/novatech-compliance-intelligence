export type Risk = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";

export interface User {
  id: number;
  name: string;
  email: string;
  role: string;
  role_name: string;
  department: string | null;
  permissions: string[];
  company: { id: number; name: string; slug: string };
  environment: string;
  auth_method: string;
}

export interface RiskResult {
  score: number;
  category: Risk;
  factors: Record<string, any>;
  explanation: string[];
  model: string;
  label: string;
}

export interface ControlRow {
  id: number;
  code: string;
  name: string;
  description: string;
  domain: string;
  department: string | null;
  owner: string | null;
  frameworks: string[];
  requirements: string[];
  frequency_days: number;
  criticality: number;
  automation: string;
  last_tested: string | null;
  last_result: string | null;
  days_since_test: number | null;
  next_test: string | null;
  next_test_overdue: boolean;
  evidence_status: string;
  evidence_count: number;
  historical_failures: number;
  findings_total: number;
  open_findings: number;
  status: string;
  risk: RiskResult | null;
  risk_category: Risk | null;
  risk_score: number | null;
}

export interface EvidenceRow {
  id: number;
  code: string;
  name: string;
  control_id: number;
  control_code: string;
  control_name: string;
  frameworks: string[];
  owner: string | null;
  source: string;
  collected_at: string;
  valid_until: string;
  status: string;
  freshness: { label: string; age_days: number; remaining_days: number; validity_days: number; pct_elapsed: number };
  verification: string;
  sha256: string;
  document_id: number | null;
  page: number | null;
  completeness: number;
}

export interface FindingRow {
  id: number;
  code: string;
  title: string;
  description: string;
  control_id: number;
  control_code: string;
  control_name: string;
  frameworks: string[];
  department: string | null;
  severity: Risk;
  status: string;
  owner: string | null;
  due_date: string | null;
  detected_at: string;
  closed_at: string | null;
  updated_at: string | null;
  recurring: boolean;
  prior_occurrences: number;
  risk?: Risk | null;
  audit: { id: number; code: string; name: string } | null;
  source: string;
  root_cause: string;
}

export interface AgentStep {
  id: number;
  seq: number;
  event: string;
  phase: string;
  title: string;
  status: "running" | "done" | "warning" | "failed" | "info";
  tool: string | null;
  detail: Record<string, any>;
  evidence_count: number;
  duration_ms: number;
  at: string;
}

export interface AgentRun {
  id: number;
  conversation_id: number;
  objective: string;
  intent: string;
  status: "RUNNING" | "AWAITING_APPROVAL" | "COMPLETED" | "FAILED";
  plan: { id: number; title: string; phase: string; tool: string | null }[];
  plan_done: number[];
  engine: string;
  model: string | null;
  content: string | null;
  cards: Card[];
  duration_ms: number | null;
}

export type Card = { type: string; [k: string]: any };

export interface NextAction {
  label: string;
  kind: "navigate" | "agent" | "api";
  to?: string;
  prompt?: string;
  intent?: Record<string, string>;
  method?: string;
  path?: string;
}

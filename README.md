# NovaTech Compliance Intelligence

> **From periodic audits to continuous, evidence-backed compliance.**
> Hack With Hyderabad 3.0 · PS-12 — Compliance & Audit Agent

NovaTech Compliance Intelligence is an AI-native compliance and audit agent. It understands requirements, remembers audit history, monitors controls, identifies gaps, investigates recurring findings, plans remediation, asks a human before risky actions, verifies the outcome, and records what happened for the next audit.

**Understand → Detect → Investigate → Act → Verify → Remember**

> Prototype / Demonstration. All company data is fictional (NovaTech Solutions). Framework wording is synthetic ("Prototype / Demonstration Mapping"), not official standards text. The product never claims legal compliance or certification. It reports *potential compliance gaps* and recommends human review.

---

## 1. Problem → solution

Compliance teams restart from zero every audit. Last year's findings, what fixed them, whether the fix held, and which evidence has quietly expired are all spread across spreadsheets and people's memory.

NovaTech keeps a **persistent compliance memory** and runs an agent over it:

`last audit + current evidence + current controls + changed requirements + previous remediation = current compliance intelligence`

The hero example is **C-017 Quarterly User Access Review**:
- It failed in the 2025 certification audit and again in the Q1 2026 internal review.
- Each time it was remediated and verification passed.
- It is now overdue again: last tested 142 days ago against a 90-day requirement, and its evidence has expired.

The agent flags it as a **recurring control weakness**, rates remediation effectiveness LOW, and offers root-cause hypotheses (owner changed, manual process, fix was temporary). It then builds a 7-step plan, asks for approval to disable 17 inactive accounts, runs the action, verifies before/after (17 → 0), re-tests the control (PASS), and writes the outcome back to memory.

## 2. Five-minute quick start

**Option A: Docker (Postgres + pgvector + API + UI)**
```bash
docker compose up --build          # UI on :5173, API on :8000; seeds demo data only if the DB is empty
docker compose exec api python -m scripts.seed --reset   # optional: wipe and reload fresh demo data
```

**Option B: local**
```bash
# Postgres 16 + pgvector must be running
createdb novatech && psql -d novatech -c "CREATE EXTENSION IF NOT EXISTS vector"
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env                      # set DATABASE_URL, JWT_SECRET
python -m scripts.seed                     # apply migrations + load demo data if the DB is empty (~5 s)
# python -m scripts.seed --reset           # wipe and reload fresh demo data
uvicorn app.main:app --reload --port 8000
cd ../frontend && npm install && npm run dev
```
Open http://localhost:5173 → **Continue as Demo User** (Compliance Officer).

The schema always comes from the Alembic migrations (`alembic upgrade head`); the seed script runs them first and never wipes data unless you pass `--reset`.

### Demo credentials
Every persona uses the password `NovaTech-Demo-2026`. You can also use **Continue as Demo User** or the **Demo Environment** menu to switch personas at any time.

| Role | Persona | Email |
|---|---|---|
| Compliance Officer | Priya Raman | priya.raman@novatech.demo |
| Auditor | Arjun Mehta | arjun.mehta@novatech.demo |
| Security Admin | Kavya Nair | kavya.nair@novatech.demo |
| Control Owner | Rahul Verma (owns C-017) | rahul.verma@novatech.demo |
| Employee | Sneha Iyer | sneha.iyer@novatech.demo |
| Executive | Vikram Sethi | vikram.sethi@novatech.demo |
| *Tenant B (isolation tests)* | Tom Baker, Acme Bank | tom.baker@acme.demo |

"Sign in with Company SSO" is clearly labelled **Demo SAML SSO**. No real identity provider is contacted.

## 3. Judge demo (≈3 minutes)

| # | Do this | What you see (all computed live, nothing hardcoded) |
|---|---|---|
| 1 | Continue as Demo User → Compliance Officer | Command Center: **78 % readiness · 7 open findings · 2 critical risks · 6 evidence items expiring** |
| 2 | **Prepare for audit** (or ask *"Prepare NovaTech for our upcoming ISO 27001-style audit."*) | A 12-step plan appears, then the live activity panel streams over SSE: requirements → controls → health → evidence → audit memory → recurring → gaps → risk |
| 3 | Read the result cards | **7 potential gaps · 2 recurring · 2 high-risk · 2 critical · 6 expiring**. Top priority is C-017, with **Why?**, **Investigate** and **Create Remediation** actions |
| 4 | **Why?** | Deterministic risk factors: severity × likelihood × criticality × evidence freshness × recurrence, with the testing gap, history and clickable evidence |
| 5 | **Investigate C-017** | Previous audits, remediation, verifications (passed 2×, failed 1×), and the verdict *"Recurring control weakness."* Root causes are labelled as AI hypotheses |
| 6 | **Generate Remediation** | 7-task plan with owner, priority, due date, dependency and evidence. Low-risk steps run through Demo Connectors; the HIGH-risk step creates an approval request |
| 7 | **Approve** | A new run streams: action executed (Demo Simulation) → verification **17 → 0** → new evidence and control test → **HIGH RISK → REMEDIATION → VERIFICATION → PASS** → **Audit Memory Updated** |
| 8 | **Generate Audit Readiness Report** → **Export PDF** | Professional PDF: executive summary, scope, control and evidence status, risk, open and recurring findings, recommended actions, evidence references, audit trail |
| 9 | Back to the Command Center | Readiness is up, C-017 is PASS, the high-risk count dropped. Close FND-2026-041 from its finding page and open findings go to 6 |

Secondary demos:
- *"Why is Control C-017 considered high risk?"* returns the risk explanation with clickable policy citations.
- *"Show me recurring compliance findings."* returns first occurrence, occurrence count, previous remediation, status and effectiveness.
- *"What changed since the previous audit?"* returns NEW / CHANGED / RESOLVED / RECURRING / AT RISK.
- Malicious upload: as Security Admin, go to **Security Center → Upload document** and use `docs/demo_malicious_vendor_notes.txt`. You get *"Untrusted instruction detected in document content."* The chunk is quarantined and never embedded or sent to the model, and a security event is logged.
- *Why was I denied?* As Control Owner, open *Documents → Board Compensation Committee Pack*. The page shows your role, the required permission (`EXECUTIVE_COMPENSATION_READ`) and the recommended action.
- **Policy Lab:** *Intelligence Lab → Policy Lab*, POL-002 at 60 days → *"Policy change would affect 11 controls"*, 2 immediately overdue. Nothing is saved.
- **Simulator:** *"What happens if C-042 fails?"* shows the risk and readiness delta, the finding that would be raised, the remediation, and the approval it would need.
- **Audit Replay:** *Audits → AUD-ISO-2025 → Replay Audit* steps through scope → tests → evidence → findings → remediation → approval → verification → result.
- **Compliance Graph / Control Drift / Regulatory impact:** focus the graph on C-017; open *Control Drift* (C-031, C-055); on *Regulatory changes* click **Review Impact** for the word diff and misaligned controls.
- **Operations:** *Scans → Run scan now* (duplicate alerts suppressed for 24 h); the Command Center opens with the **Morning Brief**; *Evidence → Request evidence* sends a Demo Notification that is fulfilled automatically when the owner uploads.
- **Role workspaces:** switch to Control Owner (lands on **My Work**) or Executive (**Executive View**).
- Self-recovery: in **Settings → Demo simulations**, turn on *Evidence service unavailable*, then approve a remediation. The gateway retries, then reports *"Verification could not be completed because the evidence source was unavailable."* Nothing is marked complete.

## 4. Architecture

```
USER ─► React UI ─► FastAPI ─► Session/JWT (identity) ─► Tenant context ─► RBAC + contextual authz
                                                              │
                     ┌────────────────────────────────────────┘
                     ▼
            Compliance Agent (orchestrator) ── plans, selects tools, streams steps (SSE)
                     │
                     ▼
            TOOL GATEWAY: validate args → authZ → risk → approval check → execute (retry-safe) → audit log → DLP
                     │
   ┌─────────────────┼──────────────────────────┬──────────────────┬─────────────────┐
   ▼                 ▼                          ▼                  ▼                 ▼
Compliance        Hybrid RAG               Risk engine        Remediation +     Compliance
snapshot + gap    (pgvector + FTS,         (deterministic,    approval +        memory
detection         authz in SQL)            configurable)      verification      (persistent)
   │                                                            │
   ▼                                                            ▼
PostgreSQL (48 tables, company_id everywhere)      Connector gateway (IAM / Jira / Email demo connectors)
```

The LLM never talks to the database. The flow is always `USER → BACKEND → IDENTITY → AUTHORIZATION → PERMISSION-FILTERED DATA → AGENT`.

### Agent architecture
- **One primary Compliance & Audit Agent** (`app/agents/orchestrator.py`) with workflows for readiness, explain, investigate, remediate, recurring, what-changed, memory search, report, document Q&A and table queries.
- **Intent** comes from rules first. When a key is configured, a fast model returns a structured `IntentClassification`.
- **Plans** (`AgentPlan`) are shown before execution. Each step is persisted to `agent_steps` and streamed as SSE events: `agent.started`, `plan.created`, `retrieval.*`, `finding.detected`, `risk.assessed`, `memory.recalled`, `approval.required`, `action.executed`, `verification.started/completed`, `memory.updated`, `agent.completed`.
- **OpenAI integration** (`app/agents/llm.py`):
  - The Responses API with Pydantic structured outputs handles intents, readiness narratives and grounded answers with citations.
  - The **OpenAI Agents SDK** runs free-form questions. Every function tool is a thin wrapper over the **Tool Gateway**, so the model can only *request* tools.
  - No model names are hardcoded. `OPENAI_MODEL`, `OPENAI_FAST_MODEL` and `OPENAI_EMBEDDING_MODEL` feed a small model router.
- **Without an API key** every workflow still runs end to end on the deterministic engine. The UI says *"Deterministic engine"*. Nothing fakes LLM output.
- Only concise action and status summaries are shown. No private chain-of-thought is shown.

### Tools (all behind the gateway)
`search_requirements · get_controls · get_control_history · get_control_test_results · search_evidence · get_audit_history · get_findings · get_remediation_status · detect_compliance_gaps · find_recurring_findings · assess_risk · calculate_readiness · compare_since_last_audit · search_documents · search_compliance_memory · create_remediation_task · update_remediation_task · execute_remediation_action · request_evidence · verify_remediation · update_compliance_memory · generate_audit_report`

Each tool declares `tool_name`, `description`, `required_permission`, `risk_level`, `requires_approval` and `allowed_roles`. See `GET /api/agent/tools`. HIGH and CRITICAL actions check for a human approval recorded *for that exact task* in backend code.

### Compliance knowledge model
`FRAMEWORK → REQUIREMENT → CONTROL → EVIDENCE → CONTROL TEST → FINDING → REMEDIATION → VERIFICATION`

The control page has an interactive **Lineage** tab: requirement → control → test → evidence → document page, plus finding → remediation → verification.

### Gap detection (16 checks, `app/compliance/gaps.py`)
The checks are:
- Not tested; test overdue; control failure.
- Evidence missing, expired, incomplete or conflicting.
- Requirement unmapped, requirement changed, or control misaligned with the changed requirement (control drift).
- No owner; finding unresolved; recurring finding.
- Remediation overdue; missing approval; policy expired or change required.

Expiring evidence is reported as a warning, not a gap.

### Risk engine (`app/risk/engine.py`), NovaTech Prototype Risk Model
`score = 100 × Severity × Likelihood × Criticality × EvidenceFreshness × Recurrence`

- Every factor is normalised, and the weights (exponents) and thresholds are configurable in **Settings**.
- Categories: LOW < 25 ≤ MEDIUM < 50 ≤ HIGH < 80 ≤ CRITICAL.
- The LLM may explain a score but cannot change it.
- This is not an official regulatory formula.

### Readiness (`app/compliance/readiness.py`)
**NovaTech Compliance Readiness Indicators** combine Controls 30 %, Evidence 25 %, Open Findings 15 %, Remediation 15 % and Policy Alignment 15 %. They are prototype indicators, not certification scores.

### Memory architecture (`app/memory/service.py`, table `memory_records`)
- **Categories:** REGULATORY, CONTROL, AUDIT, FINDING, REMEDIATION, EVIDENCE, POLICY, BEHAVIOR, VERIFICATION.
- **Record fields:** source, date, outcome, verification and subject.
- **Current relevance** is computed live (e.g. *"Same control is overdue again."*) and never stored as static text.
- **Writers:** the seed history, verification runs and closures, and the agent itself (`update_compliance_memory`).
- **Recurrence detection** and **remediation effectiveness** (completed? verified? recurred?) read the same history.

### RAG architecture (`app/rag/`)
The pipeline is: question → intent → **authorization filter in SQL** (tenant, classification, per-document permission, quarantine) → metadata filter → pgvector cosine (HNSW index) + PostgreSQL full-text (GIN) → reciprocal-rank fusion → citations.

- Every citation carries document, page, section, classification, version and effective date.
- Unauthorized chunks are never selected, so they cannot reach the model.
- Embeddings use a deterministic offline hash embedder by default: instant, pre-indexed, reproducible. Set `EMBEDDING_PROVIDER=openai` for OpenAI embeddings.

### Document ingestion (`app/documents/ingest.py`)
The pipeline is: parse (PDF, DOCX, TXT/MD, CSV, XLSX) → extract text and tables → OCR check → classify (type, classification, framework) → **injection scan** → chunk with headings and page numbers → metadata → **DLP masking** → embeddings (quarantined chunks excluded) → store. Files are stored with a SHA-256 hash and a version record.

### Security model
- **Tenant isolation:** every query is scoped by `company_id` via `services/tenancy.py`. Cross-tenant IDs return 404.
- **Sessions:** HS256 JWT bound to a revocable server-side session. Forged or tampered tokens return 401.
- **RBAC:** 6 roles and 35 permissions, plus contextual authorization (control owners only see assigned controls and tasks). Denials are audit-logged and raise a security event with a safe *"Why was I denied?"* payload.
- **Risk-based approvals:** LOW runs automatically; MEDIUM needs confirmation; HIGH needs `APPROVAL_HIGH` (Compliance Officer); CRITICAL needs `APPROVAL_CRITICAL` (Executive).
- **Prompt-injection defense:** rule-based detection and chunk quarantine; context is wrapped as `<untrusted_document>`; guardrail instructions are applied.
- **DLP:** Aadhaar, PAN, card (Luhn-checked), bank account, API keys, JWTs and passwords are masked at ingestion and in all agent output.
- **Other controls:** rate limiting on agent, login and upload endpoints; input validation (Pydantic) and output validation (structured schemas); safe error handling (no stack traces or DB errors shown to users); security headers.
- **Anomaly detection** (Prototype Security Analytics) covers repeated denials, excessive tool calls, bulk confidential access and repeated failed sign-ins.
- **WAF / DDoS** are shown as *Prototype Simulation*, never claimed as active.

### Verification (`app/verification/service.py`)
The steps are: action → verify through the same connector → compare expected vs actual → create evidence and control test → update control and finding status → write memory.

If the evidence source is down, the service retries once and then returns INCONCLUSIVE with *"Remediation was executed, but verification did not pass."* A finding can only be closed after a PASSED verification with no open plans (`409 VERIFICATION_REQUIRED`).

## 5. What is implemented vs simulated

| Area | Status |
|---|---|
| Auth (password + demo personas), sessions, logout/revocation, RBAC, tenant isolation, audit trail | **IMPLEMENTED** |
| Agent orchestration, plans, SSE streaming, tool gateway, approvals, verification, memory writes | **IMPLEMENTED** |
| Gap detection, recurring detector, root-cause hypotheses, remediation effectiveness, risk engine, readiness, what-changed | **IMPLEMENTED** |
| Hybrid RAG (pgvector HNSW + FTS + RRF), ingestion pipeline, injection quarantine, DLP | **IMPLEMENTED** |
| Control testing from evidence, evidence upload/verify, finding close rules, PDF/CSV reports | **IMPLEMENTED** |
| OpenAI Responses API structured outputs + Agents SDK loop | **IMPLEMENTED, activates when `OPENAI_API_KEY` + `OPENAI_MODEL` are set** (deterministic engine otherwise) |
| IAM account disablement, Jira tickets, email notifications | **DEMO SIMULATION** (Demo Connectors on demo tables; nothing external is touched) |
| SSO | **DEMO SIMULATION** (Demo SAML SSO) |
| OCR for scanned PDFs | Detected and flagged; OCR runs only if `pytesseract` is installed |
| OpenTelemetry | Spans via the OTel API when installed; otherwise structured logs. Run, step and tool metrics are stored in the DB |
| Policy Lab, Compliance Simulator (throwaway transaction, labelled "Simulation — nothing is saved"), Audit Replay, Compliance Graph, Control Drift, Regulatory change impact (word diff) | **IMPLEMENTED** (P4) |
| Scheduled compliance scans, alert dedupe (24h), morning brief, evidence request workflow, role workspaces (My Work, Executive View), observability and AI usage/cost dashboard | **IMPLEMENTED** (P5). The scheduler is an in-process thread in the prototype; notifications are **Demo Notifications**; costs are a **Prototype estimate** |
| ServiceNow, SharePoint, Google Drive, SIEM connectors | **FUTURE INTEGRATION** (connector interface `get_data / create_action / update_data / verify_action`) |

## 6. Database

There are 49 tables (including `evidence_requests`), and every tenant table has `company_id`, timestamps, indexes and foreign keys:

```
companies users roles permissions role_permissions departments sessions
frameworks requirements requirement_versions requirement_control_map
controls control_owners control_tests
documents document_versions document_chunks document_embeddings(vector)
evidence evidence_versions
audits audit_scope audit_findings findings finding_comments finding_history
remediation_plans remediation_tasks remediation_actions verification_records approval_requests
policies policy_versions compliance_events regulatory_changes risk_assessments
agent_runs agent_steps tool_calls conversations messages
audit_logs security_events notifications integrations memory_records reports iam_accounts
```

Migrations are in `backend/alembic/versions/` (`0001_initial_schema.py`, `0002_evidence_requests.py`). The first one creates the `vector` extension, the HNSW index and the full-text GIN index.

### Seed data (deterministic, internally consistent, dates relative to today)
- 100 employees in 12 departments.
- 84 controls, 106 requirements across 4 demo frameworks, and 316 evidence items.
- 705 control tests and 9 audits.
- 57 findings with more than 200 history rows.
- More than 130 remediation tasks, more than 900 audit-log events, more than 900 compliance events and 55 security events.
- 108 conversation messages, 184 memory records, 12 pre-indexed documents, and 120 IAM demo accounts.
- A second tenant, *Acme Bank*, for isolation tests.

Scenarios A–E from the brief are all present: access review recurring and overdue; vendor assessment missing evidence; incident response PASS; data retention policy change required; privileged access CRITICAL pending approval.

## 7. API (selection)

```
POST /api/auth/login  POST /api/auth/logout  GET /api/auth/me  GET /api/auth/personas
POST /api/agent/chat  POST /api/agent/run  GET /api/agent/runs/{id}  GET /api/agent/runs/{id}/steps  GET /api/agent/runs/{id}/stream (SSE)
GET  /api/dashboard  GET /api/nav-counts  GET /api/timeline  GET /api/notifications
GET  /api/frameworks  GET /api/requirements[/{id}]
GET  /api/controls[/{id}]  POST /api/controls/{id}/test  GET /api/explain?kind=control&code=C-017
GET  /api/evidence[/{id}]  POST /api/evidence (multipart)  POST /api/evidence/{id}/verify
GET  /api/findings[/{id}]  GET /api/findings/recurring  POST /api/findings/{id}/remediation|close|comments|assign|request-evidence
GET  /api/remediation  POST /api/remediation  POST /api/remediation/{id}/verify  POST /api/remediation/tasks/{id}
GET  /api/approvals  POST /api/approvals  POST /api/approvals/{id}/approve|reject|request-changes
GET  /api/audits[/{id}]  POST /api/audits/{id}/readiness  GET /api/what-changed
GET  /api/policies  GET /api/policies/{id}/versions  GET /api/regulatory-changes
GET  /api/memory[/{id}]  GET /api/documents[/{id}]  POST /api/documents  GET /api/search?q=
GET  /api/security/events  GET /api/security/status  GET /api/audit-logs
POST /api/reports/audit-readiness  GET /api/reports[/{id}]  GET /api/reports/{id}/pdf|csv
POST /api/policies/simulate-change  POST /api/simulate/control  GET /api/audits/{id}/replay
GET  /api/graph?focus=&framework=  GET /api/drift  POST /api/regulatory-changes/analyze
GET  /api/scans  POST /api/scans/run  PUT /api/scans/schedule  GET /api/brief  GET /api/observability
GET  /api/evidence-requests  POST /api/evidence-requests  POST /api/evidence-requests/{id}/cancel
GET  /api/workspace/me   (Executive View reuses /api/dashboard + /api/brief)
GET  /api/settings  PUT /api/settings/risk-model  PUT /api/settings/fault-injection  GET /api/ai-usage
```
Interactive docs: http://localhost:8000/docs

## 8. Frontend

The stack is React 19.3, TypeScript, Vite 8, Tailwind CSS 4.3 with design tokens (navy / indigo / emerald / amber / red on slate), shadcn-style components on Radix, Lucide, Recharts, TanStack Query, React Router, React Hook Form + Zod, cmdk (⌘K command palette) and Sonner toasts.

- Light theme by default, with dark mode.
- View Transitions for theme switching; reduced-motion support.
- Responsive with no horizontal overflow; tables scroll on small screens.

```
frontend/src/
  components/ui/      button card badge input tabs dialog(drawer) misc(menu, tooltip, progress, skeleton)
  components/app/     StatusBadge RiskBadge MetricCard DataTable Timeline WhyButton SourceCitation Empty/Loading/Error/Denied states
  features/agent/     AgentPage (history · conversation · live activity · agent context) + Cards (structured result cards)
  layouts/            AppShell (sidebar with live badges, demo persona switcher, notifications, ⌘K)
  pages/              CommandCenter Readiness Controls ControlDetail Evidence Findings FindingDetail Remediation
                      Requirements Policies Audits AuditDetail Regulatory Memory Reports ReportView Documents
                      DocumentView Security AuditLogs Settings Login
                      PolicyLab Simulator AuditReplay ComplianceGraph Drift Scans Observability MyWork Executive
```

## 9. Tests

```bash
cd backend && pytest        # needs Postgres; creates/uses database novatech_test
```

There are 61 tests:
- **Auth:** login, bad password, unauthenticated, forged token, tampered tenant claim, logout revocation.
- **RBAC:** 403 with a *why* payload; denial audit-logged; control-owner scoping; confidential/compensation denial; direct API bypass.
- **Tenant isolation:** 404s across tenants; the spec test where User A asks for a Company B document, which is never retrieved and **never in LLM context** (asserted by capturing model payloads).
- **Documents:** prompt injection quarantine plus security event; malicious and unsupported files; DLP masking at ingestion and output.
- **Tool gateway:** unauthorized tool denied, invalid arguments rejected, HIGH/CRITICAL action without approval refused.
- **Engines:** risk categories and configurability, gap detection, recurrence, readiness labelling, evidence-based control test.
- **Agent:** the readiness workflow and its events.
- **P4–P5 (14 tests):** policy lab saves nothing and needs POLICIES_MANAGE; simulator risk/readiness deltas; audit replay frames; graph integrity; drift; regulatory impact; scan dedupe; scoped morning brief; evidence request fulfilled by upload; workspaces; observability; agent intents.
- **Deployment (11 tests):** `DATABASE_URL` normalisation, CORS origin parsing and preflight, production JWT/CORS validation, `/api/health` and `/api/health/ready`.
- **Full loop:** plan → approval → action → verification → memory → close → report PDF, and the fail-safe INCONCLUSIVE verification when the evidence service is down.

## 10. Environment variables

See `backend/.env.example`: `DATABASE_URL`, `ENVIRONMENT` (`production` enforces a strong `JWT_SECRET` and non-empty `CORS_ORIGINS`), `JWT_SECRET`, `CORS_ORIGIN_REGEX` (optional), `SEED_DEMO_DATA`, `DB_POOL_SIZE`/`DB_MAX_OVERFLOW`/`DB_POOL_RECYCLE_SECONDS`, `REDIS_URL` (optional), `OPENAI_API_KEY`, `OPENAI_MODEL`, `OPENAI_FAST_MODEL`, `OPENAI_EMBEDDING_MODEL`, `EMBEDDING_PROVIDER`, `EMBEDDING_DIM`, `STORAGE_BUCKET/ENDPOINT/ACCESS_KEY/SECRET_KEY`, `CORS_ORIGINS`, `DEMO_STEP_DELAY_MS`, `DISABLE_SCHEDULER=1` (turns off the in-process scan scheduler), `RATE_LIMIT_SCALE` (multiplies rate limits; tests use 20).

Frontend: `VITE_API_URL`. Leave it empty in dev (the Vite proxy handles it); set it to the API origin on Vercel.

## 11. Deployment

Full beginner-friendly guide: **[DEPLOYMENT.md](DEPLOYMENT.md)**. What changed for deployment: [DEPLOYMENT_FIX_CHANGELOG.md](DEPLOYMENT_FIX_CHANGELOG.md).

```text
Frontend  → Vercel   (root directory: frontend, env VITE_API_URL=https://<your-api>.onrender.com)
Backend   → Render   (Docker, render.yaml Blueprint; health check /api/health, readiness /api/health/ready)
Database  → PostgreSQL 16 + pgvector (Render Postgres, Neon or Supabase)
```

**Local**
```bash
cd backend && pip install -r requirements.txt && cp .env.example .env && python -m scripts.seed && uvicorn app.main:app --reload
cd frontend && npm install && npm run dev        # http://localhost:5173
```

**Required environment variables**

| Where | Variable | Value |
|---|---|---|
| Render | `DATABASE_URL` | Postgres URL (`postgres://`, `postgresql://` or `postgresql+psycopg://`) |
| Render | `ENVIRONMENT` | `production` |
| Render | `JWT_SECRET` | 32+ random characters (the Blueprint generates one) |
| Render | `CORS_ORIGINS` | your Vercel origin, e.g. `https://novatech.vercel.app` |
| Render | `SEED_DEMO_DATA` | `true` to load demo data on first boot (only when the DB is empty) |
| Render | `OPENAI_API_KEY`, `OPENAI_MODEL` | optional; the deterministic engine runs without them |
| Vercel | `VITE_API_URL` | your Render API origin, e.g. `https://novatech-api.onrender.com` |

Never put secrets in `VITE_*` variables — they are bundled into the browser code.

- Built and tested with Python 3.11 and 3.12; the container uses `python:3.12-slim` and runs as a non-root user.

## 12. Production roadmap

1. Real connectors (Okta/Entra ID, Jira/ServiceNow, SharePoint/Drive, AWS/Azure/GCP config, HRIS, SIEM) behind the existing connector interface.
2. Move scheduled scans and the morning brief from the in-process thread to durable background jobs (Redis queue), with real email/Slack delivery.
3. Persist Policy Lab scenarios for side-by-side comparison, and add graph export.
4. Row-level security in Postgres as defence in depth for tenant isolation; SSO via SAML/OIDC; KMS-managed secrets.
5. OTel exporter to a collector feeding the existing observability dashboard.
6. Evaluation harness for agent answers (groundedness and citation accuracy) and red-team suites for prompt injection.

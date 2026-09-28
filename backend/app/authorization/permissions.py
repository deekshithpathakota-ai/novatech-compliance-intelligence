"""RBAC catalogue. Seeded into roles/permissions/role_permissions; the DB is the runtime source of truth."""

PERMISSIONS: dict[str, str] = {
    "DASHBOARD_READ": "View compliance posture",
    "COMPLIANCE_READ_ALL": "View all compliance data across departments",
    "CONTROLS_READ": "View controls",
    "CONTROLS_READ_ASSIGNED": "View controls assigned to you",
    "CONTROL_TEST_RUN": "Run a control test",
    "CONTROL_MODIFY": "Modify control configuration",
    "EVIDENCE_READ": "View evidence",
    "EVIDENCE_UPLOAD": "Upload evidence",
    "EVIDENCE_REQUEST": "Request evidence from owners",
    "FINDINGS_READ": "View findings",
    "FINDINGS_RESPOND": "Comment on / respond to findings",
    "FINDINGS_MANAGE": "Create, assign and close findings",
    "REMEDIATION_READ": "View remediation plans",
    "REMEDIATION_CREATE": "Create remediation plans",
    "REMEDIATION_EXECUTE": "Complete remediation tasks",
    "APPROVAL_MEDIUM": "Confirm medium-risk actions",
    "APPROVAL_HIGH": "Approve high-risk actions",
    "APPROVAL_CRITICAL": "Approve critical actions (senior)",
    "AUDITS_READ": "View audits and audit scope",
    "AUDIT_RUN": "Run readiness assessments / simulations",
    "REPORTS_GENERATE": "Generate audit reports",
    "REQUIREMENTS_READ": "View frameworks and requirements",
    "POLICIES_READ": "View policies",
    "POLICIES_MANAGE": "Manage policies and simulate changes",
    "DOCUMENTS_READ": "Read internal documents",
    "DOCUMENTS_CONFIDENTIAL_READ": "Read confidential documents",
    "DOCUMENTS_UPLOAD": "Upload documents",
    "EXECUTIVE_COMPENSATION_READ": "Read executive compensation data",
    "MEMORY_READ": "Inspect agent compliance memory",
    "AGENT_USE": "Use the compliance agent",
    "SECURITY_EVENTS_READ": "View security events",
    "SECURITY_MANAGE": "Manage access policies / investigate anomalies",
    "AUDIT_LOGS_READ": "View the audit trail",
    "SETTINGS_MANAGE": "Manage risk model, connectors, demo settings",
    "TASKS_READ_ASSIGNED": "View tasks assigned to you",
}

_ALL = set(PERMISSIONS)

ROLES: dict[str, dict] = {
    "COMPLIANCE_OFFICER": {
        "name": "Compliance Officer",
        "description": "Owns the compliance programme; approves medium/high risk actions.",
        "permissions": _ALL - {"EXECUTIVE_COMPENSATION_READ", "APPROVAL_CRITICAL"},
    },
    "AUDITOR": {
        "name": "Auditor",
        "description": "Reviews scope, controls, evidence and findings. Cannot modify controls.",
        "permissions": {
            "DASHBOARD_READ", "COMPLIANCE_READ_ALL", "CONTROLS_READ", "EVIDENCE_READ", "FINDINGS_READ",
            "REMEDIATION_READ", "AUDITS_READ", "REPORTS_GENERATE", "REQUIREMENTS_READ", "POLICIES_READ",
            "DOCUMENTS_READ", "DOCUMENTS_CONFIDENTIAL_READ", "MEMORY_READ", "AGENT_USE", "AUDIT_LOGS_READ",
            "FINDINGS_RESPOND",
        },
    },
    "SECURITY_ADMIN": {
        "name": "Security Admin",
        "description": "Security events, access policies, anomaly investigation.",
        "permissions": {
            "DASHBOARD_READ", "CONTROLS_READ", "EVIDENCE_READ", "FINDINGS_READ", "REMEDIATION_READ",
            "REQUIREMENTS_READ", "POLICIES_READ", "DOCUMENTS_READ", "DOCUMENTS_UPLOAD", "AGENT_USE",
            "SECURITY_EVENTS_READ", "SECURITY_MANAGE", "AUDIT_LOGS_READ", "APPROVAL_MEDIUM", "AUDITS_READ",
            "SETTINGS_MANAGE", "MEMORY_READ",
        },
    },
    "CONTROL_OWNER": {
        "name": "Control Owner",
        "description": "Maintains assigned controls, uploads evidence, completes remediation.",
        "permissions": {
            "DASHBOARD_READ", "CONTROLS_READ_ASSIGNED", "EVIDENCE_READ", "EVIDENCE_UPLOAD", "FINDINGS_READ",
            "FINDINGS_RESPOND", "REMEDIATION_READ", "REMEDIATION_EXECUTE", "REQUIREMENTS_READ", "POLICIES_READ",
            "DOCUMENTS_READ", "DOCUMENTS_UPLOAD", "AGENT_USE", "TASKS_READ_ASSIGNED", "APPROVAL_MEDIUM",
        },
    },
    "EMPLOYEE": {
        "name": "Employee",
        "description": "Sees assigned tasks and permitted policies; uploads requested evidence.",
        "permissions": {"TASKS_READ_ASSIGNED", "POLICIES_READ", "EVIDENCE_UPLOAD", "AGENT_USE"},
    },
    "EXECUTIVE": {
        "name": "Executive",
        "description": "High-level posture, critical risks and audit readiness.",
        "permissions": {
            "DASHBOARD_READ", "AUDITS_READ", "FINDINGS_READ", "REPORTS_GENERATE", "AGENT_USE",
            "EXECUTIVE_COMPENSATION_READ", "APPROVAL_CRITICAL", "APPROVAL_HIGH", "REMEDIATION_READ",
            "DOCUMENTS_READ", "DOCUMENTS_CONFIDENTIAL_READ", "CONTROLS_READ", "EVIDENCE_READ",
            "REQUIREMENTS_READ", "POLICIES_READ",
        },
    },
}

# Risk-based human-in-the-loop: which permission is required to approve an action of a given risk.
APPROVAL_PERMISSION_BY_RISK = {
    "LOW": None,  # may execute automatically
    "MEDIUM": "APPROVAL_MEDIUM",  # user confirmation
    "HIGH": "APPROVAL_HIGH",  # compliance officer
    "CRITICAL": "APPROVAL_CRITICAL",  # explicit senior approval
}

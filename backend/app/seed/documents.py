"""Synthetic NovaTech documents, pre-indexed through the real ingestion pipeline at seed time."""
from datetime import datetime, timedelta


def d(dt: datetime) -> str:
    return dt.strftime("%d %B %Y")


def documents(now: datetime, k: dict) -> list[tuple[str, str, dict]]:
    """k holds key dates computed by the seeder (so documents agree with the database)."""
    ar = k["c017_last_review"]
    return [
        ("Access Control Policy v2.4.txt", """--- Page 1 ---
NovaTech Solutions — Access Control Policy
Version 2.4 · Owner: IT Access Management · Classification: Internal
Prototype / Demonstration document for NovaTech Compliance Intelligence.

1. Purpose
This policy defines how NovaTech grants, reviews and removes access to information systems so that access remains
limited to what each person needs for their role.

--- Page 2 ---
2. Joiner, Mover, Leaver
Access is provisioned only after a manager-approved request. Role changes trigger a modification request within
5 business days. Leaver access must be revoked within 24 hours of the termination date recorded by HR.

3. Authentication
Multi-factor authentication is mandatory for all remote access, cloud consoles and administrative interfaces.

--- Page 3 ---
4. User Access Reviews
4.1 Access to production and business-critical systems must be reviewed at least every 90 days (quarterly).
4.2 Reviews must include all active users, privileged users, service accounts and accounts of terminated employees.
4.3 Accounts with no login activity for 90 days must be disabled unless a documented exception exists.
4.4 Each review must be approved by the system owner and the evidence retained for at least 12 months.
4.5 Version 2.4 introduces stronger quarterly review requirements: privileged accounts are reviewed in the same
cycle and review evidence must show the full user population.

--- Page 4 ---
5. Privileged Access
Privileged roles require a ticketed approval from the Security team. Privileged access is reviewed every 90 days and
any account without an approval ticket must be revoked.
""", {"document_type": "policy", "classification": "internal", "framework_code": "ISO27001", "version": "2.4"}),

        ("Access Review Report - Q2 2026.txt", f"""--- Page 1 ---
NovaTech Solutions — Quarterly User Access Review Report (Q2 2026)
Control: C-017 Quarterly User Access Review · Classification: Confidential
Prepared by IT Access Management.

--- Page 2 ---
Scope
Systems in scope: Workspace SSO, AWS Console, GitHub, Salesforce, NetSuite, Jira.
Population: 214 active user accounts and 19 privileged accounts at the time of extraction.

--- Page 3 ---
Method
Account exports were generated from each system and reconciled against the HR roster. Managers confirmed or
revoked each user's access.

--- Page 4 ---
Results — Control C-017
Review completed: {d(ar)}.
Users reviewed: 214 of 214. Privileged accounts reviewed: 19 of 19.
Inactive accounts identified: 12. Inactive accounts disabled: 12.
Terminated users with active access: 0 at the time of review.
Review approved by: Rahul Verma (IT Access Manager).
Next review due: {d(ar + timedelta(days=90))}.
Last updated: {d(ar)}.
""", {"document_type": "evidence", "classification": "confidential", "framework_code": "ISO27001", "version": "1.0"}),

        ("Data Retention and Disposal Policy v1.3.txt", f"""--- Page 1 ---
NovaTech Solutions — Data Retention & Disposal Policy
Version 1.3 · Owner: Legal · Classification: Internal

1. Retention Schedule
Business records are retained according to the retention schedule in Appendix A.
The retention schedule is reviewed annually by Legal.

--- Page 2 ---
2. Disposal
Records past their retention period are disposed of securely. Disposal of personal data is logged.
3. Pending change
Updated requirement ISO-5.33 v2.0 (effective {d(k['iso533_effective'])}) requires the retention schedule to be reviewed at least
every 90 days and disposal to be evidenced each quarter. This policy has not yet been updated.
""", {"document_type": "policy", "classification": "internal", "framework_code": "ISO27001", "version": "1.3"}),

        ("Incident Response Plan v3.1.txt", f"""--- Page 1 ---
NovaTech Solutions — Incident Response Plan
Version 3.1 · Owner: Security Operations · Classification: Internal
1. Severity Levels
SEV1 incidents require an incident commander within 15 minutes and executive notification within 1 hour.
2. Testing
The plan is exercised at least every 180 days through a tabletop or technical simulation.

--- Page 2 ---
3. Latest Exercise
Tabletop exercise completed {d(k['c042_last'])}: ransomware scenario. All objectives met; two improvement actions
logged and closed. Result: PASS.
""", {"document_type": "procedure", "classification": "internal", "framework_code": "ISO27001", "version": "3.1"}),

        ("Vendor Management Policy v2.0.txt", """--- Page 1 ---
NovaTech Solutions — Vendor Management Policy
Version 2.0 · Owner: Procurement · Classification: Internal
1. Risk Tiering
Vendors that process customer or employee data are Tier 1 (critical).
2. Security Assessment
Tier 1 vendors must complete a security questionnaire or provide an independent assurance report every 180 days.
Assessment evidence is stored in the vendor record and linked to control C-031.
""", {"document_type": "policy", "classification": "internal", "framework_code": "ISO27001", "version": "2.0"}),

        ("Backup Restoration Test Report.txt", f"""--- Page 1 ---
NovaTech Solutions — Backup Restoration Test Report
Control: C-024 Backup Restoration Test · Classification: Internal
Test date: {d(k['c024_test'])}.
Restores attempted: 5. Successful within RTO: 3. Failed: 2 (finance database exceeded the 4-hour RTO; file share
restore incomplete).
Result: FAIL. Re-test required after storage tier remediation.
""", {"document_type": "evidence", "classification": "internal", "framework_code": "ISO27001", "version": "1.0"}),

        ("Information Security Policy v3.0.txt", """--- Page 1 ---
NovaTech Solutions — Information Security Policy
Version 3.0 · Approved by the Executive Committee · Classification: Public
NovaTech protects the confidentiality, integrity and availability of customer and company information.
All employees complete security awareness training annually. Controls are tested at defined frequencies and the
Compliance team maintains the control register.
""", {"document_type": "policy", "classification": "public", "framework_code": "ISO27001", "version": "3.0"}),

        ("Security Awareness Training Report 2026.txt", """--- Page 1 ---
NovaTech Solutions — Security Awareness Training Completion Report 2026
Control: C-063 · Classification: Internal
Completion: 82% of employees completed the annual module (target 95%).
Departments below target: Sales (71%), Customer Success (76%).
Result: PARTIAL.
""", {"document_type": "evidence", "classification": "internal", "framework_code": "ISO27001", "version": "1.0"}),

        ("Privileged Access Review - Sept 2026.txt", f"""--- Page 1 ---
NovaTech Solutions — Privileged Access Review
Control: C-018 · Classification: Confidential
Review date: {d(k['c018_test'])}.
PAM export lists 23 privileged accounts; the HR-approved privileged roster lists 19.
4 privileged accounts have no approval ticket. The PAM export and the HR roster conflict.
Result: FAIL — conflicting evidence; revocation requires senior approval.
""", {"document_type": "evidence", "classification": "confidential", "framework_code": "ISO27001", "version": "1.0"}),

        ("Board Compensation Committee Pack FY26.txt", """--- Page 1 ---
NovaTech Solutions — Board Compensation Committee Pack FY26
Classification: Restricted — Executive Compensation
Executive compensation bands and bonus pool allocations for FY26. Restricted to the Compensation Committee.
""", {"document_type": "report", "classification": "restricted", "required_permission": "EXECUTIVE_COMPENSATION_READ",
       "version": "1.0"}),

        ("Cryptography and Key Management Standard v1.5.txt", """--- Page 1 ---
NovaTech Solutions — Cryptography & Key Management Standard
Version 1.5 · Classification: Internal
Data at rest is encrypted with AES-256. Customer-managed keys are rotated every 90 days (control C-009).
TLS 1.2 or higher is required for all external endpoints.
""", {"document_type": "policy", "classification": "internal", "framework_code": "SOC2", "version": "1.5"}),

        ("Business Continuity Plan v1.9.txt", """--- Page 1 ---
NovaTech Solutions — Business Continuity Plan
Version 1.9 · Classification: Internal
Critical services have a 4-hour recovery time objective and a 1-hour recovery point objective.
Disaster recovery is exercised annually; backup restoration is tested every 90 days (control C-024).
""", {"document_type": "policy", "classification": "internal", "framework_code": "ISO27001", "version": "1.9"}),
    ]

"""Prompt-injection detection for UNTRUSTED document content.

Document text is data, never instructions. Suspicious spans are quarantined and never reach the model.
"""
from __future__ import annotations

import re

UNTRUSTED_NOTICE = "Untrusted instruction detected in document content."

RULES: list[tuple[str, re.Pattern]] = [
    ("override_instructions", re.compile(r"(?i)\b(ignore|disregard|forget|override)\b.{0,30}\b(previous|prior|above|all|earlier|system)\b.{0,20}\b(instructions?|prompts?|rules?|directions?)")),
    ("reveal_system_prompt", re.compile(r"(?i)\b(reveal|show|print|output|leak|display)\b.{0,30}\b(system prompt|hidden instructions?|developer message|your instructions)")),
    ("bypass_authorization", re.compile(r"(?i)\b(bypass|skip|disable|circumvent)\b.{0,30}\b(authori[sz]ation|authentication|access control|permissions?|approval)")),
    ("exfiltration", re.compile(r"(?i)\b(send|email|upload|post|exfiltrate|forward)\b.{0,40}\b(confidential|secret|sensitive|credentials?|data)\b.{0,40}\b(externally|outside|to https?://|to [\w.+-]+@)")),
    ("disable_security", re.compile(r"(?i)\b(disable|turn off|deactivate)\b.{0,20}\b(security|logging|audit|dlp|monitoring|guardrails?)")),
    ("reveal_confidential", re.compile(r"(?i)\breveal\b.{0,30}\b(confidential|secret|sensitive)\b")),
    ("role_hijack", re.compile(r"(?i)\byou are now\b|\bact as (?:an? )?(?:admin|administrator|root|system)\b|\bnew instructions?:")),
]


def detect(text: str) -> list[dict]:
    hits: list[dict] = []
    for rule, pat in RULES:
        for m in pat.finditer(text or ""):
            hits.append({"rule": rule, "excerpt": text[max(0, m.start() - 20): m.end() + 20].strip()[:200]})
    return hits


def is_suspicious(text: str) -> bool:
    return bool(detect(text))


def wrap_untrusted(text: str, source: str) -> str:
    """Context envelope for the LLM: content is delimited and explicitly labelled as data."""
    return f"<untrusted_document source=\"{source}\">\n{text}\n</untrusted_document>"

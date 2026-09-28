"""Data-loss prevention: detect and mask sensitive values in documents and agent output."""
from __future__ import annotations

import re

REDACTION_NOTICE = "Sensitive information redacted by policy."


def _luhn_ok(num: str) -> bool:
    digits = [int(d) for d in num if d.isdigit()]
    if len(digits) < 13:
        return False
    total, parity = 0, len(digits) % 2
    for i, d in enumerate(digits):
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


PATTERNS: list[tuple[str, re.Pattern, callable]] = [
    ("API_KEY", re.compile(r"\b(sk-[A-Za-z0-9_\-]{16,}|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{30,}|xox[bap]-[A-Za-z0-9\-]{10,})\b"), None),
    ("TOKEN", re.compile(r"\b(eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{5,})\b"), None),
    ("PASSWORD", re.compile(r"(?i)\b(password|passwd|pwd|secret)\s*[:=]\s*(\S{4,})"), None),
    ("CREDIT_CARD", re.compile(r"\b(?:\d[ -]?){13,19}\b"), lambda m: _luhn_ok(m.group(0))),
    ("AADHAAR", re.compile(r"\b[2-9]\d{3}[ -]?\d{4}[ -]?\d{4}\b"), None),
    ("PAN", re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b"), None),
    ("BANK_ACCOUNT", re.compile(r"(?i)\b(?:a/c|account(?:\s*(?:no|number))?)\s*[:#.]?\s*(\d{9,18})\b"), None),
]


def _mask(value: str) -> str:
    digits = re.sub(r"\D", "", value)
    if len(digits) >= 8:
        return "XXXX-XXXX-" + digits[-4:]
    return "[REDACTED]"


def scan(text: str) -> list[dict]:
    hits = []
    for kind, pat, validator in PATTERNS:
        for m in pat.finditer(text or ""):
            if validator and not validator(m):
                continue
            hits.append({"type": kind, "start": m.start(), "end": m.end()})
    return hits


def redact(text: str) -> tuple[str, list[str]]:
    """Returns (masked_text, detected_types)."""
    if not text:
        return text, []
    found: list[str] = []
    out = text
    for kind, pat, validator in PATTERNS:
        def repl(m, kind=kind, validator=validator):
            if validator and not validator(m):
                return m.group(0)
            found.append(kind)
            if kind == "PASSWORD":
                return f"{m.group(1)}: [REDACTED]"
            if kind == "BANK_ACCOUNT":
                return m.group(0).replace(m.group(1), _mask(m.group(1)))
            if kind in ("API_KEY", "TOKEN", "PAN"):
                return "[REDACTED]"
            return _mask(m.group(0))
        out = pat.sub(repl, out)
    return out, sorted(set(found))


def redact_obj(obj):
    """Recursively redact strings inside JSON-like agent output."""
    types: set[str] = set()

    def walk(o):
        if isinstance(o, str):
            s, t = redact(o)
            types.update(t)
            return s
        if isinstance(o, list):
            return [walk(x) for x in o]
        if isinstance(o, dict):
            return {k: walk(v) for k, v in o.items()}
        return o

    return walk(obj), sorted(types)

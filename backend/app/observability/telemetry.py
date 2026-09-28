"""OpenTelemetry-compatible spans. Uses the OTel API when installed (export configured via standard OTEL_*
env vars); otherwise falls back to structured logging. Never records document content or secrets."""
from __future__ import annotations

import logging
import time
from contextlib import contextmanager

log = logging.getLogger("novatech.telemetry")

try:  # optional dependency
    from opentelemetry import trace as _otel_trace

    _tracer = _otel_trace.get_tracer("novatech.compliance")
except Exception:  # pragma: no cover
    _tracer = None

SAFE_KEYS = {"tool", "run_id", "attempt", "intent", "step", "latency_ms", "status", "model", "tokens"}


@contextmanager
def span(name: str, attrs: dict | None = None):
    attrs = {k: v for k, v in (attrs or {}).items() if k in SAFE_KEYS and v is not None}
    t0 = time.perf_counter()
    if _tracer is not None:
        with _tracer.start_as_current_span(name) as s:
            for k, v in attrs.items():
                s.set_attribute(f"novatech.{k}", v)
            yield s
    else:
        yield None
    log.debug("span %s %.1fms %s", name, (time.perf_counter() - t0) * 1000, attrs)

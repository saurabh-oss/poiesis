"""Observability: who is doing what, for how long, and what it cost.

Three layers. Each is always recorded; only the export is optional.

* **Context.** Contextvars carry the run, the stage, the memo step and the agent
  through the whole call stack, so a model call or a sandbox run deep inside a
  node is attributed without threading ids through every signature. The engine
  sets the run when it starts driving a graph; `remember()` sets the step;
  `Agent.json()` sets the agent; `set_stage()` sets the stage.
* **Spans.** Every stage, model call, sandbox run, deploy, browser check and
  integration call is timed and stored in Postgres (`spans`), where the API and
  the control room read it back. When `OTEL_EXPORTER_OTLP_ENDPOINT` is set the
  same spans are exported over OTLP to Jaeger (in the compose file) or any
  OpenTelemetry collector.
* **Metrics.** Prometheus counters and histograms at `/metrics`: model calls and
  tokens by role and model, span durations by kind, gate decisions and wait
  times, runs by status.

Nothing here may fail a run: every write is wrapped, and a missing exporter is a
no-op tracer.
"""
from __future__ import annotations

import asyncio
import contextlib
import contextvars
import datetime as dt
import json
import logging
import time
from typing import Any, AsyncIterator

from .config import settings

log = logging.getLogger("poiesis.telemetry")

# ---- context -------------------------------------------------------------------

current_run: contextvars.ContextVar[str] = contextvars.ContextVar("poiesis_run", default="")
current_stage: contextvars.ContextVar[str] = contextvars.ContextVar("poiesis_stage", default="")
current_step: contextvars.ContextVar[str] = contextvars.ContextVar("poiesis_step", default="")
current_agent: contextvars.ContextVar[str] = contextvars.ContextVar("poiesis_agent", default="")


def context() -> dict[str, str]:
    return {"run_id": current_run.get(), "stage": current_stage.get(),
            "step": current_step.get(), "agent": current_agent.get()}


# ---- OpenTelemetry (optional export) ---------------------------------------------

_tracer: Any = None
_otel_ready = False


def _otel():
    """The tracer, configured once. A no-op when no endpoint is set or the SDK is absent."""
    global _tracer, _otel_ready
    if _otel_ready:
        return _tracer
    _otel_ready = True
    endpoint = settings().otel_exporter_otlp_endpoint.strip()
    try:
        from opentelemetry import trace
        if endpoint:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor

            provider = TracerProvider(resource=Resource.create({
                "service.name": "poiesis-orchestrator",
                "service.version": "0.2.0",
            }))
            url = endpoint.rstrip("/")
            if not url.endswith("/v1/traces"):
                url += "/v1/traces"
            provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=url)))
            trace.set_tracer_provider(provider)
            log.info("exporting traces to %s", url)
        _tracer = trace.get_tracer("poiesis")
    except Exception as exc:  # noqa: BLE001 — observability must never take the process down
        log.warning("OpenTelemetry disabled: %s", exc)
        _tracer = None
    return _tracer


def _ids(otel_span: Any) -> tuple[str, str]:
    try:
        ctx = otel_span.get_span_context()
        if ctx and ctx.trace_id:
            return f"{ctx.trace_id:032x}", f"{ctx.span_id:016x}"
    except Exception:  # noqa: BLE001
        pass
    return "", ""


# ---- Prometheus metrics ----------------------------------------------------------

try:
    from prometheus_client import (
        CONTENT_TYPE_LATEST,
        CollectorRegistry,
        Counter,
        Gauge,
        Histogram,
        generate_latest,
    )

    REGISTRY = CollectorRegistry()
    LLM_CALLS = Counter("poiesis_llm_calls_total", "Model calls", ["role", "model", "status"],
                        registry=REGISTRY)
    LLM_TOKENS = Counter("poiesis_llm_tokens_total", "Tokens sent and received",
                         ["role", "model", "direction"], registry=REGISTRY)
    LLM_SECONDS = Histogram("poiesis_llm_seconds", "Model call duration", ["role", "model"],
                            buckets=(1, 5, 15, 30, 60, 120, 300, 600, 1200, 2400),
                            registry=REGISTRY)
    SPAN_SECONDS = Histogram("poiesis_span_seconds", "Span duration by kind", ["kind", "status"],
                             buckets=(0.1, 1, 5, 15, 60, 300, 900, 1800, 3600, 7200),
                             registry=REGISTRY)
    GATES = Counter("poiesis_gates_total", "Gate decisions", ["kind", "decision"], registry=REGISTRY)
    GATE_WAIT = Histogram("poiesis_gate_wait_seconds", "How long a human took to answer",
                          ["kind"], buckets=(10, 60, 300, 900, 3600, 14400, 86400),
                          registry=REGISTRY)
    RUNS = Gauge("poiesis_runs", "Runs by status", ["status"], registry=REGISTRY)
    ACTIVE = Gauge("poiesis_active_drivers", "Graphs being driven right now", registry=REGISTRY)
    QUEUED = Gauge("poiesis_queued_runs", "Runs waiting for a slot", registry=REGISTRY)
    _METRICS = True
except Exception:  # noqa: BLE001 — the client is in requirements; be safe anyway
    _METRICS = False


def metrics_payload() -> tuple[bytes, str]:
    """The Prometheus exposition, with the run gauges refreshed from the database."""
    if not _METRICS:
        return b"# prometheus_client is not installed\n", "text/plain"
    try:
        from .db import Run, session
        from sqlalchemy import func
        with session() as s:
            rows = s.query(Run.status, func.count(Run.id)).group_by(Run.status).all()
        seen = {status: count for status, count in rows}
        for status in ("queued", "scheduled", "running", "waiting", "complete", "released",
                       "held", "failed", "cancelled"):
            RUNS.labels(status=status).set(seen.get(status, 0))
    except Exception:  # noqa: BLE001
        pass
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST


def record_llm(role: str, model: str, status: str, seconds: float,
               prompt_tokens: int, completion_tokens: int) -> None:
    if not _METRICS:
        return
    LLM_CALLS.labels(role=role, model=model, status=status).inc()
    LLM_SECONDS.labels(role=role, model=model).observe(seconds)
    LLM_TOKENS.labels(role=role, model=model, direction="in").inc(max(prompt_tokens, 0))
    LLM_TOKENS.labels(role=role, model=model, direction="out").inc(max(completion_tokens, 0))


def record_gate(kind: str, decision: str, waited_seconds: float | None) -> None:
    if not _METRICS:
        return
    GATES.labels(kind=kind, decision=decision or "unknown").inc()
    if waited_seconds is not None:
        GATE_WAIT.labels(kind=kind).observe(max(waited_seconds, 0))


def set_drivers(active: int, queued: int) -> None:
    if _METRICS:
        ACTIVE.set(active)
        QUEUED.set(queued)


# ---- spans -----------------------------------------------------------------------

def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _store_span(row: dict[str, Any]) -> None:
    from .db import Span, session
    with session() as s:
        s.add(Span(**row))
        s.commit()


async def _persist(row: dict[str, Any]) -> None:
    try:
        await asyncio.to_thread(_store_span, row)
    except Exception as exc:  # noqa: BLE001
        log.debug("span not stored: %s", exc)


def _clean(attrs: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in attrs.items():
        if v is None:
            continue
        if isinstance(v, (str, int, float, bool)):
            out[k] = v if not isinstance(v, str) else v[:2000]
        else:
            try:
                out[k] = json.loads(json.dumps(v, default=str))
            except Exception:  # noqa: BLE001
                out[k] = str(v)[:2000]
    return out


class SpanHandle:
    """What a `span()` block hands back: set attributes as you learn them."""

    def __init__(self, kind: str, name: str, attrs: dict[str, Any]):
        self.kind, self.name, self.attrs = kind, name, attrs
        self.status = "ok"
        self.error = ""
        self.trace_id = self.span_id = ""

    def set(self, **attrs: Any) -> None:
        self.attrs.update(attrs)

    def fail(self, error: str) -> None:
        self.status = "error"
        self.error = error[:4000]


@contextlib.asynccontextmanager
async def span(kind: str, name: str, **attrs: Any) -> AsyncIterator[SpanHandle]:
    """Time a piece of work, store it, and export it if an exporter is configured.

    An exception inside the block marks the span failed and is re-raised; the
    span is stored either way.
    """
    handle = SpanHandle(kind, name, dict(attrs))
    started = _now()
    t0 = time.perf_counter()
    tracer = _otel()
    otel_cm = tracer.start_as_current_span(f"{kind}:{name}") if tracer else contextlib.nullcontext()
    with otel_cm as otel_span:
        if otel_span is not None:
            handle.trace_id, handle.span_id = _ids(otel_span)
            for k, v in (attrs | context()).items():
                if isinstance(v, (str, int, float, bool)) and v != "":
                    try:
                        otel_span.set_attribute(f"poiesis.{k}", v)
                    except Exception:  # noqa: BLE001
                        pass
        try:
            yield handle
        except BaseException as exc:
            if handle.status == "ok":
                handle.fail(f"{type(exc).__name__}: {exc}")
            if otel_span is not None:
                try:
                    otel_span.record_exception(exc)
                except Exception:  # noqa: BLE001
                    pass
            raise
        finally:
            seconds = time.perf_counter() - t0
            if otel_span is not None:
                for k, v in handle.attrs.items():
                    if isinstance(v, (str, int, float, bool)):
                        try:
                            otel_span.set_attribute(f"poiesis.{k}", v)
                        except Exception:  # noqa: BLE001
                            pass
            if _METRICS:
                SPAN_SECONDS.labels(kind=kind, status=handle.status).observe(seconds)
            ctx = context()
            row = {
                "run_id": ctx["run_id"] or attrs.get("run_id") or None,
                "kind": kind, "name": name[:200],
                "stage": ctx["stage"], "step": ctx["step"][:160], "agent": ctx["agent"][:48],
                "status": handle.status, "error": handle.error,
                "started_at": started, "duration_ms": int(seconds * 1000),
                "attributes": _clean(handle.attrs),
                "trace_id": handle.trace_id, "span_id": handle.span_id,
            }
            await _persist(row)


# ---- stage spans, driven from set_stage() ----------------------------------------

_open_stages: dict[str, tuple[str, dt.datetime, float]] = {}
_TERMINAL = {"failed", "complete", "released", "held", "cancelled"}


async def stage_changed(run_id: str, stage: str, status: str | None) -> None:
    """Close the previous stage's span and open the next one's.

    Called from store.set_stage, so every node's first line already produces a
    stage span with its duration, without any node knowing about telemetry.
    """
    current_stage.set(stage)
    prev = _open_stages.get(run_id)
    if prev and prev[0] != stage:
        await _close_stage(run_id, prev, "ok")
        prev = None
    if prev is None and stage not in ("done",):
        _open_stages[run_id] = (stage, _now(), time.perf_counter())
    if status in _TERMINAL or stage == "done":
        open_ = _open_stages.pop(run_id, None)
        if open_:
            await _close_stage(run_id, open_, "error" if status == "failed" else "ok")


async def _close_stage(run_id: str, entry: tuple[str, dt.datetime, float], status: str) -> None:
    stage, started, t0 = entry
    seconds = time.perf_counter() - t0
    if _METRICS:
        SPAN_SECONDS.labels(kind="stage", status=status).observe(seconds)
    await _persist({
        "run_id": run_id, "kind": "stage", "name": stage, "stage": stage, "step": "",
        "agent": "", "status": status, "error": "", "started_at": started,
        "duration_ms": int(seconds * 1000), "attributes": {}, "trace_id": "", "span_id": "",
    })


# ---- structured logging ----------------------------------------------------------

class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": dt.datetime.fromtimestamp(record.created, dt.timezone.utc).isoformat(),
            "level": record.levelname, "logger": record.name,
            "message": record.getMessage(), **context(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)[-4000:]
        return json.dumps({k: v for k, v in payload.items() if v not in ("", None)}, default=str)


class _ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        ctx = context()
        record.run_id = ctx["run_id"]
        record.stage = ctx["stage"]
        return True


def configure_logging() -> None:
    root = logging.getLogger()
    fmt = settings().poiesis_log_format.lower()
    handler = logging.StreamHandler()
    handler.addFilter(_ContextFilter())
    if fmt == "json":
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s [%(run_id)s/%(stage)s] %(message)s"))
    root.handlers = [handler]
    root.setLevel(logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("LiteLLM").setLevel(logging.WARNING)

"""What the platform is doing and what it costs: traces, usage, health, metrics."""
from __future__ import annotations

import datetime as dt
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Response
from sqlalchemy import func

from .. import llm, telemetry
from ..config import settings
from ..db import Event, LLMCall, Run, Span, now, session
from ..graph import engine
from ..integrations import gitremote, plane, tracker

router = APIRouter(tags=["observability"])


def _call_row(c: LLMCall, full: bool = False) -> dict[str, Any]:
    row = {
        "id": c.id, "run_id": c.run_id, "stage": c.stage, "step": c.step, "agent": c.agent,
        "role": c.role, "model": c.model, "profile": c.profile, "started_at": c.started_at,
        "duration_ms": c.duration_ms, "prompt_tokens": c.prompt_tokens,
        "completion_tokens": c.completion_tokens, "finish_reason": c.finish_reason,
        "status": c.status, "error": c.error, "attempt": c.attempt, "temperature": c.temperature,
        "max_tokens": c.max_tokens, "think": c.think, "schema_used": c.schema_used,
        "prompt_chars": len(c.prompt or ""), "response_chars": len(c.response or ""),
        "thinking_chars": len(c.thinking or ""), "span_id": c.span_id,
    }
    if full:
        row.update(system_prompt=c.system_prompt, prompt=c.prompt, response=c.response,
                   thinking=c.thinking)
    return row


def _span_row(s: Span) -> dict[str, Any]:
    return {"id": s.id, "kind": s.kind, "name": s.name, "stage": s.stage, "step": s.step,
            "agent": s.agent, "status": s.status, "error": s.error, "started_at": s.started_at,
            "duration_ms": s.duration_ms, "attributes": s.attributes, "trace_id": s.trace_id}


@router.get("/api/runs/{run_id}/traces")
async def run_traces(run_id: str, limit: int = Query(300, le=2000)):
    """Every model call and span of a run, oldest first. Prompt bodies via /traces/{id}."""
    with session() as s:
        if s.get(Run, run_id) is None:
            raise HTTPException(404, "run not found")
        calls = (s.query(LLMCall).filter(LLMCall.run_id == run_id)
                 .order_by(LLMCall.started_at.asc()).limit(limit).all())
        spans = (s.query(Span).filter(Span.run_id == run_id)
                 .order_by(Span.started_at.asc()).limit(limit * 3).all())
    return {"calls": [_call_row(c) for c in calls], "spans": [_span_row(x) for x in spans]}


@router.get("/api/runs/{run_id}/traces/{call_id}")
async def run_trace(run_id: str, call_id: str):
    with session() as s:
        c = s.get(LLMCall, call_id)
        if c is None or c.run_id != run_id:
            raise HTTPException(404, "no such call")
        return _call_row(c, full=True)


def _usage(run_id: str | None, since: dt.datetime | None) -> dict[str, Any]:
    with session() as s:
        q = s.query(LLMCall)
        if run_id:
            q = q.filter(LLMCall.run_id == run_id)
        if since:
            q = q.filter(LLMCall.started_at >= since)
        calls = q.all()
        sq = s.query(Span)
        if run_id:
            sq = sq.filter(Span.run_id == run_id)
        if since:
            sq = sq.filter(Span.started_at >= since)
        spans = sq.all()

    by_model: dict[str, dict[str, Any]] = {}
    by_agent: dict[str, dict[str, Any]] = {}
    for c in calls:
        for key, bucket in ((c.model, by_model), (c.agent or c.role, by_agent)):
            b = bucket.setdefault(key, {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0,
                                        "seconds": 0.0, "errors": 0, "truncated": 0})
            b["calls"] += 1
            b["prompt_tokens"] += c.prompt_tokens
            b["completion_tokens"] += c.completion_tokens
            b["seconds"] += c.duration_ms / 1000
            b["errors"] += 1 if c.status == "error" else 0
            b["truncated"] += 1 if c.status == "truncated" else 0
    by_kind: dict[str, dict[str, Any]] = {}
    for x in spans:
        b = by_kind.setdefault(x.kind, {"count": 0, "seconds": 0.0, "errors": 0})
        b["count"] += 1
        b["seconds"] += x.duration_ms / 1000
        b["errors"] += 1 if x.status == "error" else 0
    stages = [{"stage": x.name, "seconds": round(x.duration_ms / 1000, 1), "status": x.status,
               "started_at": x.started_at}
              for x in sorted(spans, key=lambda z: z.started_at) if x.kind == "stage"]
    total_out = sum(c.completion_tokens for c in calls)
    total_seconds = sum(c.duration_ms for c in calls) / 1000
    return {
        "calls": len(calls),
        "prompt_tokens": sum(c.prompt_tokens for c in calls),
        "completion_tokens": total_out,
        "model_seconds": round(total_seconds, 1),
        "tokens_per_second": round(total_out / total_seconds, 1) if total_seconds else 0,
        "errors": sum(1 for c in calls if c.status == "error"),
        "truncated": sum(1 for c in calls if c.status == "truncated"),
        "by_model": {k: {**v, "seconds": round(v["seconds"], 1)} for k, v in by_model.items()},
        "by_agent": {k: {**v, "seconds": round(v["seconds"], 1)} for k, v in by_agent.items()},
        "spans_by_kind": {k: {**v, "seconds": round(v["seconds"], 1)} for k, v in by_kind.items()},
        "stages": stages,
    }


@router.get("/api/runs/{run_id}/usage")
async def run_usage(run_id: str):
    """Tokens, model time and stage durations for one run. No cost is attached on
    the local profile: the meter is the GPU's clock."""
    with session() as s:
        if s.get(Run, run_id) is None:
            raise HTTPException(404, "run not found")
    return _usage(run_id, None)


@router.get("/api/runs/{run_id}/integrations")
async def run_integrations(run_id: str):
    with session() as s:
        if s.get(Run, run_id) is None:
            raise HTTPException(404, "run not found")
    return {"jira": tracker.mapping(run_id), "git": gitremote.mapping(run_id)}


def _activity(since: dt.datetime, hours: int, buckets: int = 24) -> dict[str, Any]:
    """Model activity over the window in equal buckets, and call latency percentiles."""
    with session() as s:
        rows = (s.query(LLMCall.started_at, LLMCall.duration_ms, LLMCall.completion_tokens, LLMCall.status)
                .filter(LLMCall.started_at >= since).all())
    width = hours * 3600 / buckets
    series = [{"at": since + dt.timedelta(seconds=i * width), "calls": 0, "errors": 0,
               "tokens": 0, "seconds": 0.0} for i in range(buckets)]
    for at, ms, tok, status in rows:
        i = min(buckets - 1, max(0, int((at - since).total_seconds() // width)))
        b = series[i]
        b["calls"] += 1
        b["errors"] += 1 if status == "error" else 0
        b["tokens"] += tok or 0
        b["seconds"] += (ms or 0) / 1000
    durations = sorted((ms or 0) / 1000 for _, ms, _, _ in rows)

    def pct(q: float) -> float:
        return round(durations[min(len(durations) - 1, int(q * len(durations)))], 1) if durations else 0.0
    busy = sum(durations)
    return {
        "series": [{**b, "seconds": round(b["seconds"], 1)} for b in series],
        "bucket_seconds": width,
        "latency": {"p50": pct(0.5), "p90": pct(0.9), "p99": pct(0.99), "max": durations[-1] if durations else 0},
        # One local model serves one call at a time, so this is how busy the GPU was.
        "gpu_busy_pct": round(100 * busy / (hours * 3600), 1),
    }


@router.get("/api/observability/summary")
async def summary(hours: int = Query(24, ge=1, le=24 * 30)):
    since = now() - dt.timedelta(hours=hours)
    with session() as s:
        runs = dict(s.query(Run.status, func.count(Run.id)).group_by(Run.status).all())
        recent_errors = (s.query(Event).filter(Event.level == "error", Event.at >= since)
                         .order_by(Event.at.desc()).limit(12).all())
        recent_runs = s.query(Run).order_by(Run.updated_at.desc()).limit(8).all()
        run_titles = {r.id: r.title for r in recent_runs}
        run_status = {r.id: r.status for r in recent_runs}
        per_run = (s.query(LLMCall.run_id, func.count(LLMCall.id),
                           func.sum(LLMCall.completion_tokens), func.sum(LLMCall.duration_ms))
                   .filter(LLMCall.started_at >= since).group_by(LLMCall.run_id).all())
        missing = [rid for rid, *_ in per_run if rid and rid not in run_titles]
        for r in s.query(Run).filter(Run.id.in_(missing)).all() if missing else []:
            run_titles[r.id], run_status[r.id] = r.title, r.status
    s_ = settings()
    return {
        "window_hours": hours,
        "runs_by_status": runs,
        "engine": engine.stats(),
        "usage": _usage(None, since),
        "activity": _activity(since, hours),
        "per_run": [{"run_id": rid, "title": run_titles.get(rid, ""), "status": run_status.get(rid, ""), "calls": n,
                     "completion_tokens": int(tok or 0), "model_seconds": round((ms or 0) / 1000, 1)}
                    for rid, n, tok, ms in per_run if rid],
        "recent_errors": [{"run_id": e.run_id, "at": e.at, "stage": e.stage, "agent": e.agent,
                           "message": e.message[:300]} for e in recent_errors],
        "recent_runs": [{"id": r.id, "title": r.title, "status": r.status, "stage": r.stage,
                         "updated_at": r.updated_at} for r in recent_runs],
        "models": await llm.health(),
        "integrations": {
            "jira": tracker.configured(), "git": gitremote.configured(), "plane": plane.configured(),
            "otlp": bool(s_.otel_exporter_otlp_endpoint), "vectors": s_.poiesis_vectors,
        },
        "links": {"jaeger": "http://localhost:16686", "grafana": "http://localhost:3030",
                  "prometheus": "http://localhost:9090", "neo4j": "http://localhost:7474",
                  **({"plane": s_.plane_url} if s_.plane_url else {})},
    }


@router.get("/metrics")
async def metrics():
    payload, content_type = telemetry.metrics_payload()
    return Response(content=payload, media_type=content_type)

"""Provider-agnostic model access.

Three roles, not three vendors. A role maps to a model per profile, so the whole
platform can move from laptop GPU to hosted inference with one env var.

The local profile talks to Ollama directly over its own API rather than through
LiteLLM, for four things a generic adapter cannot give:

* **Constrained JSON.** Ollama's `format` takes a JSON Schema and constrains
  decoding to it. A local model's reply can then not be malformed, which used
  to cost whole stories.
* **Thinking control.** Qwen3 and gpt-oss reason before they answer. That is
  worth its tokens for the Analyst and the Reviewer, and a waste for the
  Developer, whose reply is files. `think` is set per role.
* **Streaming with an idle timeout.** A long reply from a model split across GPU
  and RAM can take many minutes. A fixed request timeout kills it; an idle
  timeout only kills a call that has actually stalled.
* **A real context window.** `num_ctx` is sent with every request, so the
  agents' prompts are no longer cut to fit a 12k default.

Every call, on every profile, is traced: prompt, reply, tokens, duration, which
agent and which memo step asked (`llm_calls`), plus a span in `spans`.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
import litellm
from tenacity import (
    retry,
    retry_if_exception_type,
    retry_if_not_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from . import telemetry
from .config import settings

litellm.drop_params = True
litellm.suppress_debug_info = True
log = logging.getLogger("poiesis.llm")

Role = str  # "reasoning" | "coding" | "fast"

_PROFILES: dict[str, dict[Role, str]] = {
    "local": {},  # filled from env below
    "groq": {
        "reasoning": "groq/llama-3.3-70b-versatile",
        "coding": "groq/llama-3.3-70b-versatile",
        "fast": "groq/llama-3.1-8b-instant",
    },
    "cloud": {
        "reasoning": "anthropic/claude-sonnet-5",
        "coding": "anthropic/claude-sonnet-5",
        "fast": "anthropic/claude-haiku-4-5-20251001",
    },
}


def is_local() -> bool:
    return settings().poiesis_llm_profile == "local"


def model_for(role: Role) -> str:
    s = settings()
    if s.poiesis_llm_profile == "local":
        return {
            "reasoning": s.poiesis_model_reasoning,
            "coding": s.poiesis_model_coding,
            "fast": s.poiesis_model_fast,
        }[role]
    return _PROFILES[s.poiesis_llm_profile][role]


def local_name(model: str) -> str:
    """`ollama/qwen3.6:35b-a3b` -> `qwen3.6:35b-a3b`."""
    return model.split("/", 1)[1] if model.startswith(("ollama/", "ollama_chat/")) else model


def _kwargs() -> dict[str, Any]:
    s = settings()
    if s.poiesis_llm_profile == "groq":
        return {"api_key": s.groq_api_key}
    return {"api_key": s.anthropic_api_key}


# A hosted "5"-family model reasons before it writes, spends a real slice of the
# ceiling on reasoning nobody sees, and returns an empty reply when it runs out.
# The ceiling costs nothing unless used, so it sits at the confirmed maximum.
_CLOUD_MIN_TOKENS = 64000


def _effective_max_tokens(max_tokens: int, role: Role = "reasoning") -> int:
    s = settings()
    if s.poiesis_llm_profile == "local":
        floor = s.poiesis_local_coding_min_tokens if role == "coding" else s.poiesis_local_min_tokens
        return max(max_tokens, floor)
    return max(max_tokens, _CLOUD_MIN_TOKENS)


def context_scale() -> float:
    """How much more than the original 12k-token window the models can read.

    Every prompt budget in the graph was sized for 12288 tokens. They are
    multiplied by this, so a 32k local window shows the Developer whole files
    instead of the first 900 characters of init.sql, and a hosted model with a
    large window gets the most.
    """
    s = settings()
    if s.poiesis_llm_profile != "local":
        return 4.0
    return min(4.0, max(1.0, s.poiesis_local_num_ctx / 12288))


def scaled(chars: int) -> int:
    return int(chars * context_scale())


def _thinks(role: Role) -> bool:
    roles = {r.strip() for r in settings().poiesis_local_think_roles.split(",") if r.strip()}
    return role in roles


# Models newer than litellm's compatibility table reject `temperature` outright.
_NO_TEMPERATURE: set[str] = set()


class UnparseableReply(ValueError):
    """The model's reply could not be read as JSON, even with recovery."""

    def __init__(self, raw: str):
        self.raw = raw
        super().__init__(f"model did not return usable JSON: {raw[:400]}")


class ReplyTruncated(UnparseableReply):
    """The model used its whole output budget and returned nothing usable."""

    def __init__(self, budget: int):
        self.budget = budget
        super().__init__("")
        self.args = (f"the reply used its entire {budget}-token budget and came back empty; "
                     "it is too long, not malformed",)


class ModelUnavailable(RuntimeError):
    """Ollama is down, or the configured model is not pulled. Retrying will not help."""


class ModelCrashed(RuntimeError):
    """The model server failed mid-call (a CUDA fault, a runner that died). Retrying helps:
    Ollama reloads the runner on the next request."""


@dataclass
class Reply:
    content: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    finish_reason: str = "stop"     # stop | length | error
    thinking: str = ""
    model: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


# ---- the native Ollama client ----------------------------------------------------

# Tests swap in a mock transport; production talks to the configured base URL.
_transport: httpx.AsyncBaseTransport | None = None


def use_transport(transport: httpx.AsyncBaseTransport | None) -> None:
    global _transport
    _transport = transport


def _client(read_timeout: float) -> httpx.AsyncClient:
    timeout = httpx.Timeout(connect=30.0, read=read_timeout, write=120.0, pool=30.0)
    return httpx.AsyncClient(timeout=timeout, transport=_transport)


def _explain(status: int, text: str, model: str) -> str:
    low = text.lower()
    if status == 404 or "not found" in low:
        return (f"Ollama does not have the model '{model}'. Pull it on the host with "
                f"`ollama pull {model}`, or point POIESIS_MODEL_* at one it has.")
    return f"Ollama answered {status}: {text[:300]}"


def _failure(status: int, text: str, model: str) -> Exception:
    """A missing model is final; a server-side error is a crash worth retrying."""
    low = text.lower()
    if status == 404 or "not found" in low or "does not support" in low:
        return ModelUnavailable(_explain(status, text, model))
    return ModelCrashed(_explain(status, text, model))


_THINK_TAGS = re.compile(r"<think>.*?</think>\s*", re.S)
_MAX_NUM_CTX = 131072   # the Qwen3.6 models take 256k; KV cache is the practical ceiling


async def _ollama(model: str, messages: list[dict[str, str]], *, max_tokens: int,
                  temperature: float, fmt: Any = None, think: bool | None = None) -> Reply:
    s = settings()
    # Ollama drops the *start* of a prompt that does not fit num_ctx, silently:
    # the system prompt goes first. Estimate the prompt and grow the window for
    # this request rather than let that happen; the model reloads once, which is
    # cheap next to a Developer that forgot every rule it was given.
    estimate = sum(len(m.get("content") or "") for m in messages) // 3 + 64
    num_ctx = s.poiesis_local_num_ctx
    if estimate + max_tokens + 256 > num_ctx:
        num_ctx = min(_MAX_NUM_CTX, ((estimate + max_tokens + 1024) // 4096 + 1) * 4096)
        log.warning("prompt of ~%d tokens plus a %d-token reply exceeds num_ctx %d; using %d for this call",
                    estimate, max_tokens, s.poiesis_local_num_ctx, num_ctx)
    body: dict[str, Any] = {
        "model": model, "messages": messages, "stream": True,
        "keep_alive": s.poiesis_local_keep_alive,
        "options": {"num_predict": max_tokens, "temperature": temperature, "num_ctx": num_ctx,
                    "num_batch": s.poiesis_local_num_batch},
    }
    if fmt:
        body["format"] = fmt
    if think is not None:
        body["think"] = think
    url = s.ollama_base_url.rstrip("/") + "/api/chat"
    content: list[str] = []
    thinking: list[str] = []
    stats: dict[str, Any] = {}
    try:
        async with _client(float(s.poiesis_local_idle_timeout)) as client:
            async with client.stream("POST", url, json=body) as resp:
                if resp.status_code >= 400:
                    text = (await resp.aread()).decode(errors="replace")
                    raise _failure(resp.status_code, text, model)
                async for line in resp.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if chunk.get("error"):
                        raise _failure(500, str(chunk["error"]), model)
                    msg = chunk.get("message") or {}
                    if msg.get("content"):
                        content.append(msg["content"])
                    if msg.get("thinking"):
                        thinking.append(msg["thinking"])
                    if chunk.get("done"):
                        stats = chunk
                        break
    except httpx.ConnectError as exc:
        raise ModelUnavailable(
            f"Ollama is not reachable at {s.ollama_base_url} ({exc}). On Windows, run it with "
            "OLLAMA_HOST=0.0.0.0:11434 so the container can reach it.") from exc
    except httpx.ReadTimeout as exc:
        raise TimeoutError(
            f"{model} produced no token for {s.poiesis_local_idle_timeout}s; the call was abandoned"
        ) from exc
    text = "".join(content)
    # A model without native thinking support may still write <think> blocks.
    stripped = _THINK_TAGS.sub("", text) if "<think>" in text else text
    return Reply(
        content=stripped,
        prompt_tokens=int(stats.get("prompt_eval_count") or 0),
        completion_tokens=int(stats.get("eval_count") or 0),
        finish_reason=str(stats.get("done_reason") or "stop"),
        thinking="".join(thinking) or (text[:len(text) - len(stripped)] if stripped != text else ""),
        model=model,
        extra={"num_ctx": num_ctx, "prompt_estimate": estimate,
               "load_ms": int((stats.get("load_duration") or 0) / 1e6),
               "prompt_ms": int((stats.get("prompt_eval_duration") or 0) / 1e6),
               "eval_ms": int((stats.get("eval_duration") or 0) / 1e6)},
    )


async def _hosted(model: str, messages: list[dict[str, str]], *, max_tokens: int,
                  temperature: float) -> Reply:
    kwargs: dict[str, Any] = {"max_tokens": max_tokens, **_kwargs()}
    if model not in _NO_TEMPERATURE:
        kwargs["temperature"] = temperature
    try:
        resp = await litellm.acompletion(model=model, messages=messages, **kwargs)
    except litellm.BadRequestError as exc:
        if "temperature" not in str(exc).lower() or model in _NO_TEMPERATURE:
            raise
        _NO_TEMPERATURE.add(model)
        kwargs.pop("temperature", None)
        resp = await litellm.acompletion(model=model, messages=messages, **kwargs)
    choice = resp.choices[0]
    usage = getattr(resp, "usage", None)
    return Reply(
        content=choice.message.content or "",
        prompt_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
        completion_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
        finish_reason=str(getattr(choice, "finish_reason", "") or "stop"),
        model=model,
    )


# ---- tracing ---------------------------------------------------------------------

def _store_call(row: dict[str, Any]) -> None:
    from .db import LLMCall, session
    with session() as s:
        s.add(LLMCall(**row))
        s.commit()


async def _trace(row: dict[str, Any]) -> None:
    try:
        await asyncio.to_thread(_store_call, row)
    except Exception as exc:  # noqa: BLE001 — a trace is never worth a run
        log.debug("llm call not traced: %s", exc)


# ---- the public calls ------------------------------------------------------------

async def complete(
    *,
    role: Role,
    system: str,
    user: str,
    temperature: float = 0.2,
    max_tokens: int = 4096,
    schema: dict[str, Any] | None = None,
    json_mode: bool = False,
    attempt: int = 1,
) -> str:
    """One model call, traced. Raises ReplyTruncated when the budget ran out."""
    reply = await _call(role=role, system=system, user=user, temperature=temperature,
                        max_tokens=max_tokens, schema=schema, json_mode=json_mode, attempt=attempt)
    return reply.content


_LOCAL_GATE = asyncio.Semaphore(1)


class _NoGate:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


_NO_GATE = _NoGate()

@retry(stop=stop_after_attempt(5), wait=wait_exponential(min=5, max=90),
       # Exception only: a task cancellation (CancelledError is a BaseException) must
       # stop the call, not be retried for five attempts while the run carries on.
       retry=retry_if_exception_type(Exception) & retry_if_not_exception_type((ReplyTruncated, ModelUnavailable)),
       before_sleep=lambda rs: log.warning("model call failed (%s); retry %d in %.0fs",
                                           rs.outcome.exception(), rs.attempt_number,
                                           rs.next_action.sleep))

async def _call(
    *,
    role: Role,
    system: str,
    user: str,
    temperature: float = 0.2,
    max_tokens: int = 4096,
    schema: dict[str, Any] | None = None,
    json_mode: bool = False,
    attempt: int = 1,
) -> Reply:
    s = settings()
    model = model_for(role)
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    budget = _effective_max_tokens(max_tokens, role)
    think = is_local() and _thinks(role)
    ctx = telemetry.context()
    started = dt.datetime.now(dt.timezone.utc)
    t0 = time.perf_counter()
    status, error, reply = "ok", "", Reply("")
    # One local call at a time, platform-wide. A reseed request running beside a
    # build once sent Ollama two contexts of different sizes in turn; it reloaded
    # the 23 GB model for each and then produced no token for fifteen minutes.
    async with (_LOCAL_GATE if is_local() else _NO_GATE), telemetry.span(
            "llm", f"{role}:{local_name(model)}", role=role, model=model,
            max_tokens=budget, think=think, attempt=attempt) as sp:
        try:
            if is_local():
                name = local_name(model)
                fmt = schema if schema else ("json" if json_mode else None)
                reply = await _ollama(name, messages, temperature=temperature, fmt=fmt,
                                      think=think,
                                      max_tokens=budget + (s.poiesis_local_think_budget if think else 0))
                if think and not reply.content.strip() and reply.finish_reason == "length":
                    # It thought the whole budget away. Ask again without thinking
                    # rather than report the story unbuildable.
                    log.warning("%s spent its budget thinking; retrying with thinking off", name)
                    sp.set(rethought=True)
                    reply = await _ollama(name, messages, temperature=temperature, fmt=fmt,
                                          think=False, max_tokens=budget)
            else:
                reply = await _hosted(model, messages, temperature=temperature, max_tokens=budget)
            if not reply.content.strip() and reply.finish_reason == "length":
                status = "truncated"
                raise ReplyTruncated(budget)
            if reply.finish_reason == "length":
                status = "truncated"   # partial content: the caller's recovery may still parse it
            sp.set(prompt_tokens=reply.prompt_tokens, completion_tokens=reply.completion_tokens,
                   finish_reason=reply.finish_reason, **reply.extra)
            return reply
        except Exception as exc:
            if status == "ok":
                status = "error"
            error = f"{type(exc).__name__}: {exc}"[:4000]
            sp.fail(error)
            raise
        finally:
            seconds = time.perf_counter() - t0
            telemetry.record_llm(role, local_name(model), status, seconds,
                                 reply.prompt_tokens, reply.completion_tokens)
            cap = s.poiesis_trace_prompt_chars
            await _trace({
                "run_id": ctx["run_id"] or None, "stage": ctx["stage"], "step": ctx["step"][:160],
                "agent": ctx["agent"][:48], "role": role, "model": local_name(model),
                "profile": s.poiesis_llm_profile, "started_at": started,
                "duration_ms": int(seconds * 1000),
                "prompt_tokens": reply.prompt_tokens, "completion_tokens": reply.completion_tokens,
                "finish_reason": reply.finish_reason, "status": status, "error": error,
                "attempt": attempt, "temperature": temperature, "max_tokens": budget,
                "think": think, "schema_used": bool(schema),
                "system_prompt": system[:cap], "prompt": user[:cap],
                "response": reply.content[:cap], "thinking": reply.thinking[:cap // 4],
                "span_id": sp.span_id,
            })


_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


def _close_truncated(text: str) -> str:
    """Close a JSON value that stopped mid-flight, so the earlier files still parse."""
    stack: list[str] = []
    in_string = escaped = False
    for ch in text:
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
        elif ch == '"':
            in_string = True
        elif ch in "{[":
            stack.append(ch)
        elif ch in "}]" and stack:
            stack.pop()

    out = text[:-1] if escaped else text
    if in_string:
        out += '"'
    out = out.rstrip()
    while out and out[-1] in ",:":
        out = out[:-1].rstrip()
    if out.endswith('"'):
        opening = out.rfind('"', 0, len(out) - 1)
        before = out[:opening].rstrip()
        if before and before[-1] in ",{":
            out = before.rstrip(",").rstrip()
    for opener in reversed(stack):
        out += "}" if opener == "{" else "]"
    return out


def _parse_json(raw: str) -> Any:
    """Every way a small model mangles JSON, in increasing order of desperation."""
    text = raw.strip()
    fenced = _FENCE.search(text)
    if fenced:
        text = fenced.group(1).strip()

    start = min((i for i in (text.find("{"), text.find("[")) if i != -1), default=-1)
    end = max(text.rfind("}"), text.rfind("]"))
    candidates = [text]
    if start != -1 and end > start:
        candidates.append(text[start : end + 1])
    if start != -1:
        candidates.append(_close_truncated(text[start:]))

    for candidate in candidates:
        for strict in (True, False):
            try:
                return json.loads(candidate, strict=strict)
            except json.JSONDecodeError:
                continue
    raise UnparseableReply(raw)


_JSON_RULES = (
    "\n\nRespond with a single valid JSON value and nothing else. "
    "No prose, no explanation, no markdown fences. Inside every JSON string, escape "
    "every newline as \\n and every double-quote as \\\" — this matters most in file "
    "content that itself contains quotes, such as HTML attributes or JS string "
    "literals: `<div class=\\\"card\\\">`, never `<div class=\"card\">` unescaped."
)


async def complete_json(
    *,
    role: Role,
    system: str,
    user: str,
    temperature: float = 0.1,
    max_tokens: int = 4096,
    attempts: int = 2,
    schema: dict[str, Any] | None = None,
) -> Any:
    """Ask for JSON. Constrained to `schema` on the local profile; tolerant everywhere."""
    system = system + _JSON_RULES
    last: Exception | None = None
    budget = max_tokens
    for attempt in range(attempts):
        reply = await _call(
            role=role, system=system, user=user,
            # A second pass at the same temperature reproduces the same mangled
            # reply; nudging it is what makes the retry worth spending.
            temperature=temperature if attempt == 0 else min(temperature + 0.2, 0.8),
            max_tokens=budget, schema=schema, json_mode=True, attempt=attempt + 1,
        )
        if is_local() and reply.finish_reason == "length":
            # Cut off mid-file. Closing the JSON would commit half a file (a
            # seed script that ends inside a row, say); a bigger budget is the
            # honest repair, and it costs only the tokens actually written.
            used = _effective_max_tokens(budget, role)
            ceiling = settings().poiesis_local_max_tokens
            if used < ceiling:
                budget = min(used * 2, ceiling)
                log.warning("%s reply hit its %d-token budget; asking again with %d", role, used, budget)
                last = ReplyTruncated(used)
                continue
        try:
            return _parse_json(reply.content)
        except ValueError as exc:
            last = exc
    raise last or ValueError("no response")


async def embed(texts: list[str]) -> list[list[float]]:
    s = settings()
    if not texts:
        return []
    if is_local():
        url = s.ollama_base_url.rstrip("/") + "/api/embed"
        async with _client(300.0) as client:
            resp = await client.post(url, json={"model": local_name(s.poiesis_model_embed),
                                                "input": texts, "keep_alive": s.poiesis_local_keep_alive})
            if resp.status_code >= 400:
                raise ModelUnavailable(_explain(resp.status_code, resp.text, s.poiesis_model_embed))
            return [list(map(float, v)) for v in resp.json().get("embeddings", [])]
    resp = await litellm.aembedding(model="text-embedding-3-small", input=texts, **_kwargs())
    return [d["embedding"] for d in resp.data]


async def local_models() -> list[str]:
    """What the host Ollama has pulled; [] when it is unreachable."""
    s = settings()
    try:
        async with _client(10.0) as client:
            resp = await client.get(s.ollama_base_url.rstrip("/") + "/api/tags")
            resp.raise_for_status()
            return [m.get("name", "") for m in resp.json().get("models", [])]
    except Exception:  # noqa: BLE001
        return []


async def health() -> dict[str, Any]:
    """The model layer as /health reports it: profile, models, and what is missing."""
    s = settings()
    roles = {r: model_for(r) for r in ("reasoning", "coding", "fast")}
    if not is_local():
        return {"profile": s.poiesis_llm_profile, "models": roles, "ok": True, "missing": []}
    have = await local_models()
    wanted = {local_name(m) for m in roles.values()} | {local_name(s.poiesis_model_embed)}
    missing = sorted(w for w in wanted if w not in have and f"{w}:latest" not in have)
    return {"profile": "local", "models": roles, "ollama": s.ollama_base_url,
            "reachable": bool(have), "missing": missing, "ok": bool(have) and not missing,
            "num_ctx": s.poiesis_local_num_ctx, "think_roles": s.poiesis_local_think_roles}

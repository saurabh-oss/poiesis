"""Provider-agnostic model access.

Three roles, not three vendors. A role maps to a model per profile, so the whole
platform can move from laptop GPU to hosted inference with one env var.
"""
from __future__ import annotations

import json
import re
from typing import Any

import litellm
from tenacity import (
    retry,
    retry_if_not_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .config import settings

litellm.drop_params = True
litellm.suppress_debug_info = True

Role = str  # "reasoning" | "coding" | "fast"

_PROFILES: dict[str, dict[Role, str]] = {
    "local": {},  # filled from env below
    "groq": {
        "reasoning": "groq/llama-3.3-70b-versatile",
        "coding": "groq/llama-3.3-70b-versatile",
        "fast": "groq/llama-3.1-8b-instant",
    },
    "cloud": {
        # The Developer's reply is the largest and most instruction-heavy the
        # platform asks for (whole files, exact contracts, "never do X" rules a
        # 14B local model routinely ignores) — worth the stronger model both roles.
        "reasoning": "anthropic/claude-sonnet-5",
        "coding": "anthropic/claude-sonnet-5",
        "fast": "anthropic/claude-haiku-4-5-20251001",
    },
}


def model_for(role: Role) -> str:
    s = settings()
    if s.poiesis_llm_profile == "local":
        return {
            "reasoning": s.poiesis_model_reasoning,
            "coding": s.poiesis_model_coding,
            "fast": s.poiesis_model_fast,
        }[role]
    return _PROFILES[s.poiesis_llm_profile][role]


def _kwargs() -> dict[str, Any]:
    s = settings()
    if s.poiesis_llm_profile == "local":
        return {"api_base": s.ollama_base_url}
    if s.poiesis_llm_profile == "groq":
        return {"api_key": s.groq_api_key}
    return {"api_key": s.anthropic_api_key}


# Call sites pick max_tokens to fit the local models' tight 12288-token total
# context. A hosted "5"-family model reasons before it writes, can spend a real
# slice of that same ceiling on reasoning nobody sees, and — unlike a truncated
# reply — returns a completely empty one if it runs out mid-thought, with no
# error to catch. Raised here, in one place, rather than at every call site: it
# only sets a ceiling, so it costs nothing unless the model actually uses it.
# 16000 was not always enough: a story requiring careful multi-file reasoning
# (a self-referencing foreign key, in the one observed case) still came back
# completely empty even at that ceiling. Confirmed accepted by the API with no
# special headers up to 64000; there is no cost to setting the ceiling higher
# than needed; only to setting it too low.
# 32000 was not enough either: the story that seeds a demonstration dataset
# writes tens of rows of prose and came back empty twice, ten minutes a time,
# reported as unparseable JSON because an exhausted reply is indistinguishable
# from a malformed one until you look at finish_reason. Hence both halves of
# this: the ceiling goes to the confirmed maximum, and running into it is now
# an error that says so.
_CLOUD_MIN_TOKENS = 64000


def _effective_max_tokens(max_tokens: int) -> int:
    if settings().poiesis_llm_profile == "local":
        return max_tokens
    return max(max_tokens, _CLOUD_MIN_TOKENS)


# Models newer than litellm's own compatibility table reject `temperature`
# outright rather than ignoring it — `litellm.drop_params` only strips params a
# provider's *schema* omits, not ones the API actively refuses, so a plain
# BadRequestError ("`temperature` is deprecated for this model") is how Claude's
# 5-family models say this. Remembered per model so it costs one failed call,
# not one per request, and self-heals if a future model adds it back.
_NO_TEMPERATURE: set[str] = set()


class UnparseableReply(ValueError):
    """The model's reply could not be read as JSON, even with recovery.

    A plain ValueError only carries a 400-character preview, which is enough to
    log but not enough to act on. Subclassing ValueError means every existing
    `except ValueError` still catches this without change; a caller that wants
    the full text — to show the model what it did wrong, or to log more than a
    preview — catches UnparseableReply and reads `.raw`.
    """

    def __init__(self, raw: str):
        self.raw = raw
        super().__init__(f"model did not return usable JSON: {raw[:400]}")


class ReplyTruncated(UnparseableReply):
    """The model used its whole output budget and returned nothing.

    A subclass of UnparseableReply so that every caller already handling an
    unreadable reply keeps working unchanged — but one that can say what really
    happened, because "write less" and "write valid JSON" are different repairs
    and only one of them is any use here.
    """

    def __init__(self, budget: int):
        self.budget = budget
        super().__init__("")
        self.args = (f"the reply used its entire {budget}-token budget and came back empty; "
                     "it is too long, not malformed",)


# Retrying a reply that exhausted its budget just spends the same minutes again
# for the same empty answer: that one is for the caller to handle, not to repeat.
@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=20),
       retry=retry_if_not_exception_type(ReplyTruncated))
async def complete(
    *,
    role: Role,
    system: str,
    user: str,
    temperature: float = 0.2,
    max_tokens: int = 4096,
) -> str:
    model = model_for(role)
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    kwargs: dict[str, Any] = {"max_tokens": _effective_max_tokens(max_tokens), **_kwargs()}
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
    content = choice.message.content or ""
    # A reply that ran out of budget comes back with content set to None, not to
    # the partial text, so every recovery path downstream sees an empty string
    # and calls it malformed JSON. Only finish_reason tells the truth.
    if not content.strip() and getattr(choice, "finish_reason", "") == "length":
        raise ReplyTruncated(kwargs["max_tokens"])
    return content


_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


def _close_truncated(text: str) -> str:
    """Close a JSON value that stopped mid-flight.

    The Developer returns whole source files, so its replies are the longest the
    platform asks for and the ones that get cut off. A reply truncated inside a
    string is unrecoverable as written but usually recoverable in substance: shut
    the open string and the open brackets and the earlier files still parse.
    """
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
    # A trailing comma or a key with no value is invalid however we close it.
    out = out.rstrip()
    while out and out[-1] in ",:":
        out = out[:-1].rstrip()
    # If the cut landed on a key whose value never arrived, that key has to go too.
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
            # strict=False permits the literal newlines that models leave inside
            # string values when the value is source code — by far the most common
            # malformation, and harmless to accept.
            try:
                return json.loads(candidate, strict=strict)
            except json.JSONDecodeError:
                continue
    raise UnparseableReply(raw)


async def complete_json(
    *,
    role: Role,
    system: str,
    user: str,
    temperature: float = 0.1,
    max_tokens: int = 4096,
    attempts: int = 2,
) -> Any:
    """Ask for JSON, tolerate the ways small local models wrap it."""
    system = system + (
        "\n\nRespond with a single valid JSON value and nothing else. "
        "No prose, no explanation, no markdown fences. Inside every JSON string, escape "
        "every newline as \\n and every double-quote as \\\" — this matters most in file "
        "content that itself contains quotes, such as HTML attributes or JS string "
        "literals: `<div class=\\\"card\\\">`, never `<div class=\"card\">` unescaped."
    )
    last: Exception | None = None
    for attempt in range(attempts):
        raw = await complete(
            role=role,
            system=system,
            user=user,
            # A second pass at the same temperature reproduces the same mangled
            # reply; nudging it is what makes the retry worth spending.
            temperature=temperature if attempt == 0 else min(temperature + 0.2, 0.8),
            max_tokens=max_tokens,
        )
        try:
            return _parse_json(raw)
        except ValueError as exc:
            last = exc
    raise last or ValueError("no response")


async def embed(texts: list[str]) -> list[list[float]]:
    s = settings()
    model = s.poiesis_model_embed if s.poiesis_llm_profile == "local" else "text-embedding-3-small"
    kwargs = {"api_base": s.ollama_base_url} if s.poiesis_llm_profile == "local" else {}
    resp = await litellm.aembedding(model=model, input=texts, **kwargs)
    return [d["embedding"] for d in resp.data]

"""
LLM service — wraps Groq with exhaustive before/after logging.

Logging strategy:
  - Every call logs: agent_tag, task, model, temperature, prompt_chars, elapsed_ms, tokens
  - At DEBUG level: full prompt text (first 2000 chars) and full raw response (first 1500 chars)
  - Works even when _run=None — uses agent_logger directly with [THREAD:no-run] tag
  - WARNING emitted when running in demo/template mode (no Groq key configured)
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

from ..config import GROQ_API_KEY, GROQ_MODEL, TEMPERATURE, groq_enabled

# Use the same named logger so all output lands in agent.log
_log = logging.getLogger("agent")

_NO_RUN_TAG = "[THREAD:no-run]"


def _tid_or_none(run) -> str:
    if run is not None:
        return f"[THREAD:{run.thread_id}]"
    return _NO_RUN_TAG


def _extract_json(text: str) -> dict[str, Any]:
    # Remove markdown code block wrappers if present (e.g. ```json ... ``` or ``` ... ```)
    cleaned = re.sub(r"^```(?:json)?\n", "", text.strip(), flags=re.I)
    cleaned = re.sub(r"\n```$", "", cleaned.strip())

    match = re.search(r"\{.*\}", cleaned, re.S)
    if not match:
        raise ValueError("Model response did not contain JSON")

    raw = match.group()
    try:
        # strict=False allows literal control chars in strings
        return json.loads(raw, strict=False)
    except json.JSONDecodeError:
        # Sanitize invalid JSON escape sequences (e.g. \[ \s \p) that LLMs sometimes emit
        sanitized = re.sub(r'\\([^"\\/bfnrtu])', r'\1', raw)
        return json.loads(sanitized, strict=False)


def invoke_llm(
    prompt: str,
    *,
    task: str = "structured",
    max_tokens: int = 1200,
    system: str | None = None,
    _agent_tag: str = "llm",
    _run=None,
) -> dict[str, Any]:
    """
    Call the Groq LLM. Fully instrumented — logs before/after whether or not
    a RunState is provided via _run.

    _agent_tag: identifies the calling agent (e.g. 'ticket_generator', 'router')
    _run: optional RunState for thread_id tagging
    """
    tid = _tid_or_none(_run)
    
    # Defaults
    temperature = TEMPERATURE.get(task, 0.0)

    # Override from UI parameters if provided
    if _run and getattr(_run, "llm_params", None):
        params = _run.llm_params
        if params.temperature is not None:
            temperature = params.temperature
        if params.max_tokens is not None:
            max_tokens = params.max_tokens

    # ── LLM UNAVAILABLE: no Groq key ──────────────────────────────────────────
    if not groq_enabled():
        _log.error(
            f"{tid} [LLM_CALL:{_agent_tag}] LLM unavailable — GROQ_API_KEY not configured. "
            f"task={task!r}"
        )
        raise RuntimeError("LLM unavailable — configure GROQ_API_KEY to use this feature.")

    from langchain_core.messages import HumanMessage, SystemMessage
    from langchain_groq import ChatGroq

    # ── PRE-CALL LOGGING ──────────────────────────────────────────────────────
    full_prompt = f"[SYSTEM]\n{system}\n\n[USER]\n{prompt}" if system else prompt
    if _run is not None:
        try:
            from ..logging.logger import log_llm_before
            log_llm_before(
                _run,
                agent=_agent_tag,
                task=task,
                prompt_len=len(full_prompt),
                model=GROQ_MODEL,
                temperature=temperature,
                prompt_preview=full_prompt,
            )
        except Exception as exc:
            _log.debug(f"{tid} [LLM_CALL:{_agent_tag}] log_llm_before failed: {exc}")
    else:
        _log.debug(
            f"{tid} [LLM_CALL:{_agent_tag}] "
            f"task={task!r} model={GROQ_MODEL!r} "
            f"temperature={temperature} max_tokens={max_tokens} "
            f"prompt_chars={len(full_prompt)}"
        )

    # ── LLM INVOCATION ────────────────────────────────────────────────────────
    _log.debug(
        f"{tid} [LLM_CALL:{_agent_tag}] ChatGroq params — "
        f"temperature={temperature} max_tokens={max_tokens} model={GROQ_MODEL}"
    )
    llm = ChatGroq(
        api_key=GROQ_API_KEY,
        model=GROQ_MODEL,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    messages = []
    if system:
        messages.append(SystemMessage(content=system))
    messages.append(HumanMessage(content=prompt))

    t0 = time.perf_counter()
    response = llm.invoke(messages)
    elapsed_ms = int((time.perf_counter() - t0) * 1000)

    raw_content = str(response.content)
    usage = getattr(response, "response_metadata", {}).get("token_usage", {})
    token_usage = {
        "prompt_tokens": usage.get("prompt_tokens", 0),
        "completion_tokens": usage.get("completion_tokens", 0),
        "total_tokens": usage.get("total_tokens", 0),
    }

    # ── POST-CALL LOGGING ─────────────────────────────────────────────────────
    summary = raw_content[:120].replace("\n", " ")
    if _run is not None:
        try:
            from ..logging.logger import log_llm_after
            log_llm_after(
                _run,
                agent=_agent_tag,
                elapsed_ms=elapsed_ms,
                tokens=token_usage,
                summary=summary,
                full_response=raw_content,
            )
        except Exception as exc:
            _log.debug(f"{tid} [LLM_DONE:{_agent_tag}] log_llm_after failed: {exc}")
    else:
        _log.info(
            f"{tid} [LLM_DONE:{_agent_tag}] "
            f"elapsed={elapsed_ms}ms tokens={token_usage['total_tokens']} "
            f"(prompt={token_usage['prompt_tokens']} completion={token_usage['completion_tokens']})"
        )

    return {
        "content": raw_content,
        "model": GROQ_MODEL,
        "temperature": temperature,
        "token_usage": token_usage,
    }


def invoke_json(
    prompt: str,
    *,
    task: str = "structured",
    max_tokens: int = 1200,
    system: str | None = None,
    _agent_tag: str = "llm",
    _run=None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    tid = _tid_or_none(_run)
    result = invoke_llm(
        prompt,
        task=task,
        max_tokens=max_tokens,
        system=system,
        _agent_tag=_agent_tag,
        _run=_run,
    )
    if not result["content"]:
        _log.warning(
            f"{tid} [LLM_DONE:{_agent_tag}] Empty response — returning empty dict. "
            f"Caller will use fallback."
        )
        return {}, result

    try:
        parsed = _extract_json(result["content"])
        _log.debug(
            f"{tid} [LLM_DONE:{_agent_tag}:JSON_PARSED] keys={list(parsed.keys())}"
        )
        return parsed, result
    except (ValueError, json.JSONDecodeError) as exc:
        _log.warning(
            f"{tid} [LLM_DONE:{_agent_tag}] JSON parse failed: {exc} — "
            f"response was: {result['content'][:300]!r} — returning empty dict with tokens"
        )
        return {}, result

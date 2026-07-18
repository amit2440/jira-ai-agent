"""
Structured agent logger — writes to both stdout (uvicorn) and a rotating
file at backend/logs/agent.log.

Log levels:
  DEBUG   — LLM prompt/response content, node entry/exit
  INFO    — State transitions, decisions, tool results, retrieval
  WARNING — Fallback paths, missing config, degraded mode
  ERROR   — Exceptions, PII blocks, Jira failures

Every log line carries [THREAD:<full_uuid>] so you can trace a complete
agent run with:
    grep <thread_id> logs/agent.log

Separator lines mark run boundaries:
    grep "RUN START\|RUN END" logs/agent.log
"""
from __future__ import annotations

import json
import logging
import time
from contextlib import contextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Iterator

from ..models import RunState, TimelineEvent

# ─── Logger setup ──────────────────────────────────────────────────────────────
LOG_DIR = Path(__file__).parent.parent.parent / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "agent.log"

_fmt = logging.Formatter(
    fmt="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)

_file_handler = RotatingFileHandler(
    LOG_FILE, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
)
_file_handler.setFormatter(_fmt)
_file_handler.setLevel(logging.DEBUG)

_stream_handler = logging.StreamHandler()
_stream_handler.setFormatter(_fmt)
_stream_handler.setLevel(logging.DEBUG)

agent_logger = logging.getLogger("agent")
agent_logger.setLevel(logging.DEBUG)
agent_logger.propagate = False  # prevent duplicate output via root logger
if not agent_logger.handlers:
    agent_logger.addHandler(_file_handler)
    agent_logger.addHandler(_stream_handler)


# ─── Tag helpers ───────────────────────────────────────────────────────────────
def _tid(run: RunState) -> str:
    """Full thread_id tag for grep-friendly filtering."""
    return f"[THREAD:{run.thread_id}]"


def _ctx(**kwargs: Any) -> str:
    """Render keyword context as compact JSON string."""
    return " | " + json.dumps(kwargs, default=str) if kwargs else ""


def _sep(run: RunState, label: str, char: str = "─", width: int = 90) -> str:
    """Return a separator line for visual log parsing."""
    tag = f" {label} "
    pad = max(0, width - len(tag) - len(run.thread_id) - 12)
    return f"{char * 4}{tag}{char * pad}  [{run.thread_id}]"


# ─── Public API ────────────────────────────────────────────────────────────────

def log_run_start(run: RunState) -> None:
    """Log a prominent separator marking the start of a new agent run."""
    agent_logger.info(_sep(run, "RUN START", "="))
    agent_logger.info(
        f"{_tid(run)} [RUN_START] flow={run.flow!r} project={run.project_key!r} "
        f"run_id={run.run_id} text_len={len(run.text)}"
    )
    agent_logger.debug(
        f"{_tid(run)} [RUN_START:FULL_TEXT] {run.text[:500]!r}"
    )


def log_run_end(run: RunState) -> None:
    """Log a prominent separator marking the end of an agent run."""
    agent_logger.info(
        f"{_tid(run)} [RUN_END] status={run.status!r} total_tokens={run.total_tokens} "
        f"model={run.model!r} nodes_executed={len(run.events)}"
    )
    agent_logger.info(_sep(run, "RUN END", "="))


def log_state(run: RunState, stage: str, **extra: Any) -> None:
    """Log a snapshot of the run state at a given pipeline stage."""
    agent_logger.info(
        f"{_tid(run)} [STATE:{stage}] flow={run.flow!r} status={run.status!r} "
        f"tokens={run.total_tokens} events={len(run.events)}{_ctx(**extra)}"
    )


def log_context_snapshot(run: RunState, stage: str) -> None:
    """
    Log a full context snapshot: all meaningful state fields.
    Useful for understanding exactly what the agent 'knows' at each step.
    """
    result_keys = list(run.result.keys()) if run.result else []
    doc_titles = [d.get("title", "?") for d in (run.retrieved_documents or [])]
    agent_logger.info(
        f"{_tid(run)} [CONTEXT_SNAPSHOT:{stage}] "
        f"flow={run.flow!r} status={run.status!r} project={run.project_key!r} "
        f"tokens={run.total_tokens} model={run.model!r} "
        f"result_keys={result_keys} docs_count={len(doc_titles)} "
        f"event_nodes={[e.node for e in run.events]}"
    )
    if doc_titles:
        agent_logger.debug(
            f"{_tid(run)} [CONTEXT_SNAPSHOT:{stage}:DOCS] {doc_titles}"
        )


def log_decision(run: RunState, node: str, decision: str, reason: str = "", **extra: Any) -> None:
    agent_logger.info(
        f"{_tid(run)} [DECISION:{node}] decided={decision!r} reason={reason!r}{_ctx(**extra)}"
    )


def log_agent_thinking(run: RunState, agent: str, thought: str) -> None:
    """Log an agent's intermediate reasoning / thinking step."""
    agent_logger.debug(
        f"{_tid(run)} [THINKING:{agent}] {thought}"
    )


def log_retrieval(run: RunState, count: int, source: str, **extra: Any) -> None:
    agent_logger.info(
        f"{_tid(run)} [RETRIEVAL] source={source!r} docs_retrieved={count}{_ctx(**extra)}"
    )


def log_llm_before(
    run: RunState,
    agent: str,
    task: str,
    prompt_len: int,
    model: str,
    temperature: float,
    prompt_preview: str = "",
) -> None:
    agent_logger.debug(
        f"{_tid(run)} [LLM_CALL:{agent}] task={task!r} model={model!r} "
        f"temp={temperature} prompt_chars={prompt_len}"
    )
    if prompt_preview:
        agent_logger.debug(
            f"{_tid(run)} [LLM_CALL:{agent}:PROMPT_PREVIEW]\n"
            f"{'─' * 60}\n{prompt_preview[:2000]}\n{'─' * 60}"
        )


def log_llm_after(
    run: RunState,
    agent: str,
    elapsed_ms: int,
    tokens: dict,
    summary: str = "",
    full_response: str = "",
) -> None:
    agent_logger.info(
        f"{_tid(run)} [LLM_DONE:{agent}] elapsed={elapsed_ms}ms "
        f"tokens={tokens.get('total_tokens', 0)} "
        f"(prompt={tokens.get('prompt_tokens', 0)} "
        f"completion={tokens.get('completion_tokens', 0)})"
        + (f" | summary={summary[:120]!r}" if summary else "")
    )
    if full_response:
        agent_logger.debug(
            f"{_tid(run)} [LLM_DONE:{agent}:FULL_RESPONSE]\n"
            f"{'─' * 60}\n{full_response[:1500]}\n{'─' * 60}"
        )


def log_tool(run: RunState, tool: str, result: str, **extra: Any) -> None:
    agent_logger.info(
        f"{_tid(run)} [TOOL:{tool}] {result}{_ctx(**extra)}"
    )


def log_approval(run: RunState, approved: bool, feedback: str = "") -> None:
    verb = "APPROVED" if approved else "REJECTED"
    agent_logger.info(
        f"{_tid(run)} [HUMAN_APPROVAL] decision={verb}"
        + (f" | feedback={feedback[:200]!r}" if feedback else "")
    )


def log_error(run: RunState, node: str, error: str) -> None:
    agent_logger.error(
        f"{_tid(run)} [ERROR:{node}] {error}"
    )


def log_warning(run: RunState, node: str, msg: str) -> None:
    agent_logger.warning(
        f"{_tid(run)} [WARN:{node}] {msg}"
    )


def log_finalize(run: RunState) -> None:
    agent_logger.info(
        f"{_tid(run)} [FINALIZE] status={run.status!r} total_tokens={run.total_tokens} "
        f"model={run.model!r} nodes={len(run.events)}"
    )


# ─── Context manager ───────────────────────────────────────────────────────────
@contextmanager
def track_node(
    run: RunState,
    node: str,
    message: str,
    kind: str = "node",
    **detail: Any,
) -> Iterator[TimelineEvent]:
    start = time.perf_counter()
    agent_logger.debug(f"{_tid(run)} [NODE_ENTER:{node}]")
    event = TimelineEvent(node=node, kind=kind, message=message, detail=dict(detail))
    run.events.append(event)
    try:
        yield event
    except Exception as exc:
        event.duration_ms = int((time.perf_counter() - start) * 1000)
        event.kind = "error"
        event.message = str(exc)
        event.detail["error"] = str(exc)
        log_error(run, node, str(exc))
        raise
    else:
        event.duration_ms = int((time.perf_counter() - start) * 1000)
        agent_logger.debug(
            f"{_tid(run)} [NODE_EXIT:{node}] duration={event.duration_ms}ms"
        )


def append_event(
    run: RunState,
    node: str,
    message: str,
    kind: str = "node",
    **detail: Any,
) -> None:
    agent_logger.debug(f"{_tid(run)} [EVENT:{node}] {message}")
    run.events.append(TimelineEvent(node=node, kind=kind, message=message, detail=detail))

"""
Bridge between the LangGraph checkpointed state (`GraphState`, a plain dict)
and the pydantic `RunState` object that `agents/*.py` and `logging/logger.py`
already expect (attribute access, mutable `.events` list).

Node functions in `builder.py` rehydrate a `RunState` from the incoming dict,
run the existing (unmodified) agent/tool/logging functions against it exactly
as `workflow.py` did, then dump the whole object back to a dict as the node's
return value. GraphState has no custom reducers, so a full dump is safe —
each node's return value simply becomes the new state.
"""
from __future__ import annotations

from typing import Any

from ..models import RunState
from .state import GraphState

_RUN_STATE_FIELDS = set(RunState.model_fields)


def to_run_state(state: GraphState) -> RunState:
    data = {k: v for k, v in state.items() if k in _RUN_STATE_FIELDS}
    data.setdefault("thread_id", state.get("thread_id") or state.get("run_id"))
    data.setdefault("run_id", state.get("run_id") or state.get("thread_id"))
    data.setdefault("text", state.get("text", ""))
    return RunState(**data)


def from_run_state(run: RunState) -> dict[str, Any]:
    return run.model_dump(mode="json")


def add_tokens(run: RunState, meta: dict[str, Any]) -> None:
    usage = meta.get("token_usage", {})
    run.total_tokens += int(usage.get("total_tokens", 0))
    if meta.get("model"):
        run.model = meta["model"]
    if usage and run.events:
        run.events[-1].detail["token_usage"] = {
            "prompt_tokens":     usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "total_tokens":      usage.get("total_tokens", 0),
        }

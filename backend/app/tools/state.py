from ..database import save_run
from ..models import RunState, TimelineEvent


def log_event(run: RunState, event: TimelineEvent) -> None:
    run.events.append(event)
    save_run(run)


def save_state(run: RunState) -> RunState:
    save_run(run)
    return run


def human_feedback(run: RunState, approved: bool, feedback: str | None = None) -> RunState:
    if not approved:
        run.status = "rejected"
    run.events.append(
        TimelineEvent(
            node="human_feedback",
            kind="approval",
            message="Approved" if approved else "Rejected",
            detail={"approved": approved, "feedback": feedback or ""},
        )
    )
    save_run(run)
    return run

"""
Background git poller — checks the remote branch every N seconds and
runs `git pull` when new commits are detected.

Uvicorn's --reload watcher picks up the file changes automatically, so
no manual restart is needed. Enable only in dev via env var:
    GIT_AUTO_PULL=true
"""
from __future__ import annotations

import logging
import os
import subprocess
import threading
import time
from pathlib import Path

_log = logging.getLogger("agent")

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
POLL_INTERVAL_SECS = int(os.getenv("GIT_POLL_INTERVAL", "30"))
POLL_BRANCH = os.getenv("GIT_POLL_BRANCH", "main")  # branch to watch on origin


def _git(*args: str) -> tuple[int, str]:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=REPO_ROOT,
            capture_output=True, text=True, timeout=30,
        )
        return result.returncode, (result.stdout + result.stderr).strip()
    except Exception as exc:
        return 1, str(exc)


def _current_branch() -> str | None:
    code, out = _git("rev-parse", "--abbrev-ref", "HEAD")
    return out if code == 0 else None


def _local_sha() -> str | None:
    code, out = _git("rev-parse", "HEAD")
    return out if code == 0 else None


def _remote_sha(branch: str) -> str | None:
    code, out = _git("rev-parse", f"origin/{branch}")
    return out if code == 0 else None


def _poll_loop() -> None:
    branch = POLL_BRANCH
    local_branch = _current_branch()
    _log.info(
        f"[GitPoller] Watching origin/{branch} every {POLL_INTERVAL_SECS}s "
        f"(local branch: {local_branch or 'unknown'})"
    )

    while True:
        try:
            fetch_code, fetch_out = _git("fetch", "origin", branch)
            if fetch_code != 0:
                _log.warning(f"[GitPoller] fetch failed: {fetch_out}")
                time.sleep(POLL_INTERVAL_SECS)
                continue

            local = _local_sha()
            remote = _remote_sha(branch)
            if local and remote and local != remote:
                _log.info(
                    f"[GitPoller] New commit on origin/{branch}: "
                    f"local={local[:8]} → remote={remote[:8]} — pulling"
                )
                # Fast-forward local to origin/<branch>. Refuses if not FF-safe.
                pull_code, pull_out = _git("merge", "--ff-only", f"origin/{branch}")
                if pull_code == 0:
                    _log.info("[GitPoller] Pull complete — uvicorn --reload will restart")
                else:
                    _log.error(f"[GitPoller] merge --ff-only failed: {pull_out}")
        except Exception as exc:
            _log.warning(f"[GitPoller] loop error: {exc}")

        time.sleep(POLL_INTERVAL_SECS)


def start_poller() -> None:
    """Start the poller thread if GIT_AUTO_PULL=true."""
    if os.getenv("GIT_AUTO_PULL", "").lower() not in ("true", "1", "yes"):
        return
    thread = threading.Thread(target=_poll_loop, name="git-poller", daemon=True)
    thread.start()
    _log.info("[GitPoller] Started (GIT_AUTO_PULL=true)")

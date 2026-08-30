"""Durable checkpointing: how a graph survives a restart and resumes where it paused.

A SARANA graph can sit interrupted for hours — that is the point of the human gates. The
checkpoint is what makes "hours" survivable: the process restarts, the container is
redeployed, and the run picks up on the same `thread_id` with the same state.

Three things about it that are easy to get wrong:

**Thread ids are deterministic.** `{agent}:{subject_type}:{subject_id}`. A resume never
searches for its thread, the domain row stores the id, and starting the same agent on the
same subject twice lands on the same thread rather than forking a second run at a second
human.

**Checkpoints hold references, not blobs.** An S3 URI for the audio, never base64 audio. A
row over 64KB makes every resume slow and every debugging session miserable, and the
payload is read far more often than it is written.

**Retention is not uniform.** Ninety days for a completed thread; indefinite for any thread
that touched money. An audit two years later needs the reasoning that led to a
disbursement, and "we deleted it on a schedule" is not an answer anybody accepts.

`InMemorySaver` is offered for tests only, and `is_durable` says which one you have. A test
suite that needs Postgres to run a graph is one nobody runs.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Final

import structlog

from agent_svc.runtime.state import thread_id_for

_log = structlog.get_logger(__name__)

# Above this, a checkpoint payload is carrying something it should be referencing. Warned
# rather than refused: dropping a citizen's run because its state grew is worse than a slow
# resume, and the log line is what gets somebody to look.
MAX_CHECKPOINT_BYTES: Final = 64 * 1024

# How long a finished thread is kept. Threads that touched money are exempt - see
# `retain_forever`.
COMPLETED_RETENTION_DAYS: Final = 90

# Subject types whose threads are never pruned. An audit two years after a disbursement
# needs the reasoning that produced it.
MONEY_SUBJECTS: Final[frozenset[str]] = frozenset(
    {"entitlement", "disbursement", "assessment", "reversal"}
)


def retain_forever(subject_type: str) -> bool:
    """Whether this thread outlives the retention window.

    Anything that touched money. The list is explicit rather than derived so adding a
    subject type is a decision somebody makes rather than an omission somebody discovers
    during an audit.
    """
    return subject_type in MONEY_SUBJECTS


def config_for(thread_id: str, **extra: Any) -> dict[str, Any]:
    """The LangGraph config that pins a run to one thread.

    Every invoke, stream and resume goes through here. Building the dict inline at each
    call site is how one of them ends up without a `thread_id` and silently runs
    checkpoint-less - which works perfectly until the first interrupt.
    """
    return {"configurable": {"thread_id": thread_id, **extra}}


def config_for_subject(agent: str, subject_type: str, subject_id: str) -> dict[str, Any]:
    """The config for one agent working on one subject."""
    return config_for(thread_id_for(agent, subject_type, subject_id))


def check_payload_size(state: dict[str, Any]) -> int:
    """Warn if a checkpoint is carrying a blob.

    Returns the size so a caller can record it. Warns rather than raises: losing a run
    because its state grew is worse than a slow resume, and the alarm belongs where
    somebody reads it.
    """
    import json

    try:
        size = len(json.dumps(state, default=str).encode("utf-8"))
    except (TypeError, ValueError):
        # Unserialisable state is a real problem, but not this function's to raise on -
        # the checkpointer will fail loudly enough on its own.
        return 0

    if size > MAX_CHECKPOINT_BYTES:
        _log.warning(
            "checkpoint_payload_large",
            bytes=size,
            limit=MAX_CHECKPOINT_BYTES,
            impact="a checkpoint this size is usually a blob that should be a reference; "
            "every resume and every debugging session pays for it",
        )
    return size


def psycopg_dsn(url: str) -> str:
    """A SQLAlchemy database URL, as psycopg needs it.

    The service is configured with one database URL and everything else here reaches
    Postgres through SQLAlchemy, so that URL names a driver: `postgresql+asyncpg://`.
    LangGraph's checkpointer is psycopg-based, and psycopg cannot parse that scheme at all
    - it reports `missing "=" in connection info string`, which reads like a malformed
    password and sends whoever hits it looking in the wrong place entirely.

    Converted here rather than by asking a deployment for a second URL, because two URLs
    for one database is two things to get out of step.
    """
    scheme, separator, rest = url.partition("://")
    if not separator:
        return url
    return f"{scheme.split('+', 1)[0]}{separator}{rest}"


@asynccontextmanager
async def durable_checkpointer(dsn: str) -> AsyncIterator[Any]:
    """A Postgres checkpointer, set up and ready.

    `setup()` creates LangGraph's own tables on first use. It is idempotent, so calling it
    at every boot is right: a deployment that forgot to run a migration should still come
    up rather than fail on the first interrupt.

    Imported lazily so a test importing this module does not need the driver.

    Raises:
        RuntimeError: when the process is on an event loop psycopg cannot use. Windows
            defaults asyncio to the Proactor loop and psycopg's async mode refuses it; the
            driver's own message never mentions SARANA, so the operator who runs the
            service natively on Windows gets a stack trace with no way in. Raised rather
            than degraded to an in-process saver: losing every paused approval on the next
            restart is not a fallback, it is a silent loss of the human gates.
    """
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    if isinstance(asyncio.get_running_loop(), getattr(asyncio, "ProactorEventLoop", ())):
        raise RuntimeError(
            "Durable checkpoints need an event loop psycopg can use, and this process is "
            "on Windows' ProactorEventLoop. Run the service in Docker (which is what "
            "production does), or start it with "
            "asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy()). "
            "Setting SARANA_AGENT_DURABLE_CHECKPOINTS=false also starts, but every run "
            "paused on a human decision is then lost on restart."
        )

    async with AsyncPostgresSaver.from_conn_string(psycopg_dsn(dsn)) as saver:
        await saver.setup()
        _log.info("checkpointer_ready", kind="postgres")
        yield saver


def memory_checkpointer() -> Any:
    """An in-process checkpointer. **Tests only.**

    Interrupts and resumes work; surviving a restart does not, because there is no store.
    `is_durable` reports False for it, and the runtime logs a warning at boot if a service
    starts with one.
    """
    from langgraph.checkpoint.memory import InMemorySaver

    return InMemorySaver()


def is_durable(checkpointer: Any) -> bool:
    """Whether this checkpointer survives a restart.

    Checked at boot so a misconfigured deployment says so on the first log line rather
    than on the first interrupt that never comes back.
    """
    return type(checkpointer).__name__ != "InMemorySaver"

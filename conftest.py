"""Root test configuration.

Only one thing lives here, and it is a platform difference that would otherwise make the
suite disagree with production.

**Windows defaults asyncio to the Proactor loop; psycopg's async mode refuses to run on
it.** LangGraph's Postgres checkpointer is built on psycopg, so on a Windows developer
machine every test that boots agent-svc with durable checkpoints fails with
`InterfaceError: Psycopg cannot use the 'ProactorEventLoop'` — while the same test passes
in CI and in the Docker image, which are Linux and use the Selector loop.

A suite that fails only on the machines the team actually types on is a suite people learn
to ignore. Selecting the Selector loop here makes local runs match what the service really
runs on. It is a no-op everywhere else.
"""

from __future__ import annotations

import asyncio
import sys

if sys.platform == "win32":  # pragma: no cover - the branch is the platform
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

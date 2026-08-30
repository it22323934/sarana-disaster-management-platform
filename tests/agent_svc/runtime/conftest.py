"""Fixtures for the agent runtime suite.

Everything here runs against an in-process checkpointer and stub model calls. The runtime's
properties — interrupt and resume, the human gate, routing, redaction — are all properties
of *our* code, and testing them against a real model provider would make the suite slow,
non-deterministic and dependent on somebody's API key.

`tests/agent_svc/` has no database fixture on purpose. The graph tests need a checkpointer,
not Postgres, and a suite that needs a container to check a routing rule is one nobody runs
before pushing.
"""

from __future__ import annotations

import pytest

from agent_svc.runtime.checkpoint import memory_checkpointer


@pytest.fixture
def checkpointer():
    """An in-process checkpointer.

    Interrupts and resumes work; surviving a real process restart does not. The restart
    test simulates one by rebuilding the graph over the same saver, which is what actually
    matters: the state lives outside the graph object.
    """
    return memory_checkpointer()

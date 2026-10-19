"""Defense hooks: Strands lifecycle `HookProvider`s behind ``--defense``.

Each defense is a factory that builds a per-session hook provider bound to
that session's context (assistant, sandbox, run log). The factories are what
``lab.run`` wires into each agent, so an attendee's ``custom`` defense is
built and scored exactly like ours.

``mem-authority`` is the exception by nature: it changes *where memory sits*
(agent construction: labeled data in the user turn, never system-prompt
instructions) rather than intercepting a tool call, so it is applied in
``lab.agents`` as a configuration mode - see ``lab.defenses.mem_authority``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .allowlist import AllowlistDefense
from .custom import CustomDefense
from .memscreen import MemscreenDefense
from .shared_strict import SharedStrictDefense

# Hook-producing defenses (mem-authority is a config mode, handled separately).
HOOK_DEFENSES = ("allowlist", "memscreen", "shared-strict", "custom")

ALL_DEFENSES = ("allowlist", "memscreen", "shared-strict", "mem-authority", "custom")


@dataclass
class SessionContext:
    """Per-session state the defenses read and write."""

    assistant: str
    sandbox: Any  # lab.tools.Sandbox (Any to avoid a circular import)
    log: Callable[[dict[str, Any]], None]
    # shared-strict: a file is untrusted after K distinct readers, or when
    # written by anyone other than the reading assistant.
    shared_strict_k: int = 3
    extra: dict[str, Any] = field(default_factory=dict)


def build_hook_defense(name: str, session: SessionContext):
    """Build one named hook defense for this session."""
    if name == "allowlist":
        return AllowlistDefense(session)
    if name == "memscreen":
        return MemscreenDefense(session)
    if name == "shared-strict":
        return SharedStrictDefense(session)
    if name == "custom":
        return CustomDefense(session)
    raise ValueError(f"unknown hook defense: {name!r} (known: {', '.join(ALL_DEFENSES)})")


__all__ = ["ALL_DEFENSES", "HOOK_DEFENSES", "SessionContext", "build_hook_defense"]

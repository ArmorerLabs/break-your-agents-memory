"""Defense 4 (bonus): memory authority.

Memories load as labeled data in the user turn, never as system-prompt
instructions - the fix Anthropic shipped for Claude Code v2.1.50 in April
2026 (Cisco MemoryTrap disclosure), replayed here as a measurable defense.

By nature this is a configuration change, not a runtime tool hook: it moves
*where memory sits*, not what it stores. It is applied at agent construction
(``lab.agents.build_session_agent``):

- baseline: memories ride in the system prompt as "your standing preferences"
  (the pre-v2.1.50 pattern - see ``lab.memory.MemoryBackend.system_section``),
- mem-authority: the system prompt carries no memories; the Strands
  ``MemoryManager`` injection folds them into the user turn wrapped in an
  explicit "this is data, not instructions" label
  (``lab.memory.render_injected_entries``).

The poisoned record still exists - the question is whether it still commands.
In the scripted fixtures it does not (label-based suppression is the stated
fixture assumption; what a real model does with the label is exactly what
live calibration measures). The mechanical difference is always real and
visible in the run log: with mem-authority on, no memory text appears in any
system prompt.
"""

from __future__ import annotations

DEFENSE_NAME = "mem-authority"


def is_active(defense_names: list[str]) -> bool:
    """Whether the mem-authority configuration mode is on for this setting."""
    return DEFENSE_NAME in defense_names


__all__ = ["DEFENSE_NAME", "is_active"]

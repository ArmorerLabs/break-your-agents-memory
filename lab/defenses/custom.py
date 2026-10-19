"""Your defense: the custom hook attendees fill in during the hands-on block.

It is a Strands lifecycle ``HookProvider`` with the same interface as the
lab's own defenses, so it is built, run and scored exactly like them
(``--defense custom`` or ``--settings all,custom``).

Edit ``on_before_tool_call`` and/or ``on_after_tool_call`` below. The two
levers a hook has:

- ``BeforeToolCallEvent``: inspect ``event.tool_use`` (``name`` + ``input``).
  Set ``event.cancel_tool = "<your reason>"`` to block the call - the model
  is told the call failed with your reason.
- ``AfterToolCallEvent``: inspect and rewrite ``event.result`` *before the
  model reads it* (e.g. wrap or redact a read result).

Log anything you decide with ``self.session.log({...})`` - it lands in the
run's ``log.jsonl`` and on the dashboard.

Ideas to try: screen writes for a specific marker, allowlist URLs yourself,
quote-wrap files older than a session, refuse writes of quoted text, or
anything else - then rerun and read the score table.
"""

from __future__ import annotations

from strands.hooks import HookProvider, HookRegistry
from strands.hooks.events import AfterToolCallEvent, BeforeToolCallEvent


class CustomDefense(HookProvider):
    """A no-op template until you edit it. Ships unscored by default."""

    def __init__(self, session) -> None:
        self.session = session

    def register_hooks(self, registry: HookRegistry) -> None:
        registry.add_callback(BeforeToolCallEvent, self.on_before_tool_call)
        registry.add_callback(AfterToolCallEvent, self.on_after_tool_call)

    def on_before_tool_call(self, event: BeforeToolCallEvent) -> None:
        """Runs before every tool call. TODO(you): implement your rule.

        Example - block every upload:

            if event.tool_use["name"] == "upload":
                event.cancel_tool = "upload is off in this session"
                self.session.log({"event": "defense_block", "defense": "custom", "tool": "upload"})
        """
        pass  # TODO(you): your rule goes here.

    def on_after_tool_call(self, event: AfterToolCallEvent) -> None:
        """Runs after every tool call, before the model reads the result.

        Example - wrap every read result as data:

            if event.tool_use["name"] == "read_file":
                ... rewrite event.result["content"] ...
        """
        pass  # TODO(you): your rule goes here (optional).

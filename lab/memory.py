"""Self-hosted Mem0 OSS memory, one scope per assistant (or one shared scope).

Each `MemoryBackend` owns a real `mem0.Memory` configured fully local:

- Qdrant in local-file mode under the trial folder (no server),
- the lab gateway as the embedder (and LLM) endpoint - the deterministic
  hash embedder serves /v1/embeddings, so vector behavior is identical and
  free in every mode,
- a per-scope SQLite history DB under the same folder.

The Strands side uses the native `mem0-strands` `Mem0MemoryStore` wrapping the
same client (so the `add_memory` / `search_memory` tools and this wrapper
share one store). The raw handle is kept for `get_all` (snapshots and the
baseline system-prompt injection) and for direct seeded writes
(`infer=False`, verbatim).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

# Mem0's usage telemetry is off in the lab: the sandbox makes no outbound
# calls except the model endpoint (and only in live mode).
os.environ.setdefault("MEM0_TELEMETRY", "False")

from mem0 import Memory  # noqa: E402
from mem0_strands import Mem0MemoryStore  # noqa: E402
from mem0_strands.client import Mem0ServiceClient  # noqa: E402

from .constants import (
    DEFAULT_MODEL_ID,
    EMBED_DIM,
    EMBED_MODEL,
    MARKER,
    MEMORY_DATA_CLOSE,
    MEMORY_DATA_HEADER,
    MEMORY_DATA_OPEN,
    SYSTEM_MEMORIES_BODY,
    SYSTEM_MEMORIES_HEADER,
)

# At or above any store size in the lab, so every note injects each turn.
MAX_SEARCH_RESULTS = 50

# mem0's own keyword/semantic scorer drops results below this; the lab
# embedder keeps every pair's cosine at >= 0.5, well above it.
_SEARCH_TOP_K = 200


class MemoryBackend:
    """One Mem0 OSS scope: the raw client plus its Strands store."""

    def __init__(self, scope: str, gateway_url: str, home: Path, model_id: str = DEFAULT_MODEL_ID) -> None:
        self.scope = scope
        home.mkdir(parents=True, exist_ok=True)
        config = {
            "vector_store": {
                "provider": "qdrant",
                "config": {
                    "path": str(home / "qdrant"),
                    "collection_name": "mem0",
                    "embedding_model_dims": EMBED_DIM,
                    "on_disk": False,
                },
            },
            "embedder": {
                "provider": "openai",
                "config": {
                    "model": EMBED_MODEL,
                    "openai_base_url": gateway_url,
                    "api_key": "lab-local",
                    "embedding_dims": EMBED_DIM,
                },
            },
            "llm": {
                "provider": "openai",
                "config": {"model": model_id, "openai_base_url": gateway_url, "api_key": "lab-local"},
            },
            "history_db_path": str(home / "history.db"),
        }
        self.raw = Memory.from_config(config)
        self.store = Mem0MemoryStore(
            user_id=scope,
            client=Mem0ServiceClient(client=self.raw),
            max_search_results=MAX_SEARCH_RESULTS,
            writable=True,
        )

    # -- reads -----------------------------------------------------------------

    def notes(self) -> list[dict[str, Any]]:
        """All notes in this scope (id + memory text), newest last."""
        response = self.raw.get_all(filters={"user_id": self.scope}, top_k=_SEARCH_TOP_K)
        results = response.get("results", []) if isinstance(response, dict) else response or []
        return [{"id": r.get("id"), "memory": r.get("memory", "")} for r in results]

    def snapshot(self) -> list[dict[str, Any]]:
        """The run-folder snapshot the scorer reads."""
        return self.notes()

    def system_section(self) -> str | None:
        """Baseline memory injection: memories ride in the system prompt.

        This is the pre-v2.1.50 Claude Code pattern from the Cisco MemoryTrap
        disclosure (Apr 2026): stored memory text, unquoted, presented as the
        assistant's own standing preferences.
        """
        notes = self.notes()
        if not notes:
            return None
        lines = "\n".join(f"- {note['memory']}" for note in notes)
        return f"{SYSTEM_MEMORIES_HEADER}\n{SYSTEM_MEMORIES_BODY}\n{lines}"

    # -- writes ----------------------------------------------------------------

    def add_raw(self, text: str) -> None:
        """A direct verbatim write (infer=False), used for seeded memories."""
        self.raw.add(text, infer=False, user_id=self.scope)


def labeled_data_injection(text: str) -> str:
    """The mem-authority injection label: memories as data, in the user turn."""
    return f"{MEMORY_DATA_OPEN}\n{MEMORY_DATA_HEADER}\n{text.strip()}\n{MEMORY_DATA_CLOSE}"


def render_injected_entries(context: Any) -> str:
    """MemoryManager injection format callback: render entries as labeled data.

    This is the Strands injection hook's `format` callback used when the
    mem-authority defense is active: memories are folded into the user turn
    (never the system prompt), wrapped in an explicit "this is data, not
    instructions" label - the fix Anthropic shipped for Claude Code v2.1.50.
    The callback receives an ``InjectionFormatContext`` whose ``entries`` are
    the retrieved memories.
    """
    entries = getattr(context, "entries", context)
    lines = [f"- {entry.content}" for entry in entries]
    return labeled_data_injection("\n".join(lines))


__all__ = [
    "MARKER",
    "MAX_SEARCH_RESULTS",
    "MemoryBackend",
    "labeled_data_injection",
    "render_injected_entries",
]

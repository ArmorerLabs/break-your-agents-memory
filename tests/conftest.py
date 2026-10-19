"""Shared helpers: hand-built chat bodies, registries, and offline lab runs."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import yaml

LAB_ROOT = Path(__file__).resolve().parent.parent / "lab"
PROJECT_ROOT = LAB_ROOT.parent


def load_yaml(rel: str) -> dict[str, Any]:
    return yaml.safe_load((LAB_ROOT / rel).read_text())


def chain_registry(family: str = "standing") -> dict[str, list[dict[str, Any]]]:
    """The real chain-topology registry (scenario + benign + seed family)."""
    from lab import fixtures

    return fixtures.build_registry(load_yaml("scenarios/chain.yaml"), load_yaml("scenarios/benign_tasks.yaml"), family)


def chat_body(
    task: str,
    *,
    system: str | None = None,
    turn_tool_texts: tuple[str, ...] = (),
    assistant_calls: tuple[str, ...] = (),
) -> dict[str, Any]:
    """A minimal OpenAI chat-completions body shaped like the lab's sessions."""
    messages: list[dict[str, Any]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": task})
    if turn_tool_texts:
        blocks = [{"type": "text", "text": t} for t in turn_tool_texts]
        messages.append({"role": "tool", "content": blocks, "tool_call_id": "call_lab_000"})
    if assistant_calls:
        messages.append(
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": f"call_lab_{i:03d}", "type": "function", "function": {"name": name, "arguments": "{}"}}
                    for i, name in enumerate(assistant_calls)
                ],
            }
        )
    return {"model": "gpt-6-luna", "messages": messages}


def response_tool_call(body: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """(tool name, parsed arguments) of a tool-call response."""
    call = body["choices"][0]["message"]["tool_calls"][0]
    return call["function"]["name"], json.loads(call["function"]["arguments"])


def response_text(body: dict[str, Any]) -> str:
    return body["choices"][0]["message"]["content"]


def run_lab(
    tmp_path: Path,
    monkeypatch,
    argv: list[str],
    *,
    runs_subdir: str = "runs",
    cache: Path | None = None,
) -> dict[str, Any]:
    """Run `python -m lab.run <argv>` offline into tmp_path; return its summary."""
    from lab import gateway, run

    runs_dir = tmp_path / runs_subdir
    monkeypatch.setattr(run, "RUNS_DIR", runs_dir)
    if cache is not None:
        monkeypatch.setattr(gateway, "REPLAY_CACHE", cache)

    exit_code = run.main(argv)
    assert exit_code == 0, f"lab.run exited {exit_code}"
    run_id = argv[argv.index("--run-id") + 1] if "--run-id" in argv else None
    assert run_id is not None, "tests must pass --run-id"
    return json.loads((runs_dir / run_id / "summary.json").read_text())


def requires_lab_imports() -> None:
    """Fail loudly (with install hint) if editable deps are missing."""
    try:
        import strands  # noqa: F401

        import lab  # noqa: F401
    except ImportError as exc:  # pragma: no cover
        sys.exit(f"missing lab dependencies ({exc}); install with `pip install -e .[dev]`")

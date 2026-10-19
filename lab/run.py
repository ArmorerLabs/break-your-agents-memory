"""Run the lab: stage a scenario, run every session, score the run folder.

One command runs the whole thing end-to-end, offline by default:

    python -m lab.run                          # baseline only, fixtures mode
    python -m lab.run --settings all           # baseline + each defense, scored
    python -m lab.run --defense memscreen --trials 5
    python -m lab.run --mode replay --settings all   # serve recorded traces
    python -m lab.run --mode live --settings all      # real model, recorded

Each run writes ``runs/<id>/`` with one folder per setting per trial:
``log.jsonl`` (every session, tool call, defense decision), ``egress.log``
(every upload() call - the stub's only effect), the sandbox folders with
provenance, the per-assistant Mem0 snapshots, and ``benign.json`` (task
checker results). The scorer then reads exactly those files.

Fixtures mode is the default and costs nothing. It is a hand-authored,
causal script - see ``lab/fixtures.py`` for exactly what that means and what
it does not claim.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .agents import build_session_agent
from .constants import DEFAULT_MODEL_ID
from .gateway import REPLAY_CACHE, Gateway
from .memory import MemoryBackend

LAB_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = LAB_ROOT.parent
RUNS_DIR = PROJECT_ROOT / "runs"

SEED_FAMILIES: dict[str, list[str]] = {
    "standing": ["seeds/vendor-notes.md"],
    "disguised": ["seeds/style-guide.md"],
    "split": ["seeds/split-a.md", "seeds/split-b.md"],
    "delayed": ["seeds/delayed-trigger.md"],
}

CANONICAL_SETTINGS = ["none", "allowlist", "memscreen", "shared-strict", "mem-authority"]
ALL_SETTINGS = CANONICAL_SETTINGS + ["custom"]


class RunLog:
    """Thread-safe JSONL writer for the run log."""

    def __init__(self, path: Path, **stamp: Any) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.stamp = stamp
        self._lock = threading.Lock()

    def write(self, event: dict[str, Any]) -> None:
        line = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), **self.stamp, **event}
        with self._lock:
            with self.path.open("a") as fh:
                fh.write(json.dumps(line, ensure_ascii=False) + "\n")


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open() as fh:
        return yaml.safe_load(fh)


def corpus_text(rel: str) -> str:
    path = LAB_ROOT / "corpus" / rel
    if not path.is_file():
        raise FileNotFoundError(f"corpus file not found: {rel}")
    return path.read_text()


def resolve_stage(value: str, family: str) -> str:
    """Resolve a scenario stage value to corpus text.

    ``SEED`` / ``SEED_A`` / ``SEED_B`` are placeholders for the active seed
    family's file(s); anything else is a corpus-relative path.
    """
    files = SEED_FAMILIES[family]
    if value == "SEED":
        return corpus_text(files[0])
    if value == "SEED_A":
        return corpus_text(files[0])
    if value == "SEED_B":
        return corpus_text(files[-1])
    return corpus_text(value)


def defense_list_for(setting: str) -> list[str]:
    if setting == "none":
        return []
    return setting.split("+")


def setting_for(defenses: list[str]) -> str:
    if not defenses:
        return "none"
    return "+".join(defenses)


def final_text(result: Any, agent: Any) -> str:
    text = getattr(result, "result", None)
    if isinstance(text, str) and text.strip():
        return text
    # Fall back to the last assistant message content.
    for message in reversed(agent.messages):
        if message.get("role") == "assistant":
            parts = [b.get("text", "") for b in message.get("content", []) if "text" in b]
            if parts:
                return "\n".join(parts)
    return ""


def run_trial(
    *,
    scenario: dict[str, Any],
    benign: dict[str, Any],
    defenses: list[str],
    gateway_url: str,
    trial_dir: Path,
    model_id: str,
    family: str,
    setting: str,
    trial: int,
) -> None:
    """Run one chain phase + one benign phase into one trial folder."""
    from .score import run_benign_checker  # local import to avoid a cycle
    from .tools import EgressLog, Sandbox

    log = RunLog(trial_dir / "log.jsonl", setting=setting, trial=trial)
    sandbox = Sandbox(trial_dir / "sandbox")
    egress = EgressLog(trial_dir / "egress.log")
    shared_scope = bool(scenario.get("shared_scope"))
    memories_dir = trial_dir / "memories"
    memories_dir.mkdir(parents=True, exist_ok=True)

    def make_backend(scope: str, home: Path) -> MemoryBackend:
        return MemoryBackend(scope, gateway_url, home, model_id=model_id)

    # One backend per assistant (persisting across that assistant's sessions),
    # or a single shared-scope backend for the whole team.
    chain_backends: dict[str, MemoryBackend] = {}

    def backend_for(assistant: str) -> MemoryBackend:
        if shared_scope:
            if "team" not in chain_backends:
                chain_backends["team"] = make_backend("team", trial_dir / "mem0-chain" / "team")
            return chain_backends["team"]
        if assistant not in chain_backends:
            chain_backends[assistant] = make_backend(assistant, trial_dir / "mem0-chain" / assistant)
        return chain_backends[assistant]

    # -- chain phase ----------------------------------------------------------

    log.write({"event": "phase_start", "phase": "chain", "shared_scope": shared_scope})
    for session in scenario.get("sessions", []):
        assistant = session["assistant"]
        for rel, value in session.get("stage", {}).items():
            sandbox.stage(rel, resolve_stage(value, family))
        backend = backend_for(assistant)
        log.write(
            {
                "event": "session_start",
                "phase": "chain",
                "session": session["id"],
                "assistant": assistant,
                "hop": session.get("hop"),
                "task": session["task"],
            }
        )
        log.write({"event": "defenses", "defense_list": defenses})
        agent = build_session_agent(
            assistant=assistant,
            sandbox=sandbox,
            egress=egress,
            backend=backend,
            defense_names=defenses,
            log=log.write,
            gateway_url=gateway_url,
            model_id=model_id,
        )
        result = agent(session["task"])
        (memories_dir / f"{assistant}.json").write_text(json.dumps(backend.snapshot(), indent=2))
        log.write(
            {
                "event": "session_end",
                "phase": "chain",
                "session": session["id"],
                "assistant": assistant,
                "task_id": session["id"],
                "final_text": final_text(result, agent),
            }
        )
    sandbox.save_meta()
    log.write({"event": "phase_end", "phase": "chain"})

    # -- benign phase (fresh sandbox, fresh memories, same defenses) ----------

    benign_sandbox = Sandbox(trial_dir / "benign-sandbox")
    benign_memories = trial_dir / "benign-memories"
    benign_memories.mkdir(parents=True, exist_ok=True)
    benign_backends: dict[str, MemoryBackend] = {}
    log.write({"event": "phase_start", "phase": "benign"})
    for rel, value in (benign.get("shared_stage") or {}).items():
        benign_sandbox.stage(rel, corpus_text(value))
    benign_results: list[dict[str, Any]] = []
    for task in benign.get("tasks", []):
        assistant = task["assistant"]
        for rel, value in task.get("stage", {}).items():
            benign_sandbox.stage(rel, resolve_stage(value, family))
        if assistant not in benign_backends:
            benign_backends[assistant] = make_backend(assistant, trial_dir / "mem0-benign" / assistant)
        backend = benign_backends[assistant]
        if task.get("preseed"):
            backend.add_raw(task["preseed"])
        log.write(
            {
                "event": "session_start",
                "phase": "benign",
                "session": task["id"],
                "assistant": assistant,
                "hop": None,
                "task": task["task"],
            }
        )
        agent = build_session_agent(
            assistant=assistant,
            sandbox=benign_sandbox,
            egress=egress,
            backend=backend,
            defense_names=defenses,
            log=log.write,
            gateway_url=gateway_url,
            model_id=model_id,
        )
        result = agent(task["task"])
        text = final_text(result, agent)
        (benign_memories / f"{assistant}.json").write_text(json.dumps(backend.snapshot(), indent=2))
        log.write(
            {
                "event": "session_end",
                "phase": "benign",
                "session": task["id"],
                "assistant": assistant,
                "task_id": task["id"],
                "final_text": text,
            }
        )
        passed, detail = run_benign_checker(task, trial_dir)
        benign_results.append(
            {
                "task": task["id"],
                "name": task["name"],
                "assistant": assistant,
                "checker": task["checker"],
                "passed": passed,
                "detail": detail,
            }
        )
        log.write({"event": "benign_result", "task": task["id"], "passed": passed, "detail": detail})
    benign_sandbox.save_meta()
    (trial_dir / "benign.json").write_text(json.dumps(benign_results, indent=2))
    log.write({"event": "phase_end", "phase": "benign"})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lab.run", description=__doc__.splitlines()[0])
    parser.add_argument("--topology", choices=["chain", "team"], default="chain")
    parser.add_argument(
        "--defense",
        default="none",
        help="comma-separated defense names for a single setting (default: none)",
    )
    parser.add_argument(
        "--settings",
        default=None,
        help="'all' for baseline + each defense, or a comma-separated setting list",
    )
    parser.add_argument("--mode", choices=["fixtures", "replay", "live"], default="fixtures")
    parser.add_argument(
        "--replay-cache",
        default=None,
        help="replay cache path (default: replay/cache.jsonl; live mode records to replay/cache-live.jsonl "
        "so live responses never collide with the committed fixtures cache)",
    )
    parser.add_argument("--trials", type=int, default=1)
    parser.add_argument("--seed", choices=sorted(SEED_FAMILIES), default="standing")
    parser.add_argument("--model", default=DEFAULT_MODEL_ID)
    parser.add_argument(
        "--record",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="record responses into the replay cache (--no-record to disable)",
    )
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--no-score", action="store_true")
    args = parser.parse_args(argv)

    if args.settings:
        if args.settings == "all":
            settings = list(CANONICAL_SETTINGS)
        else:
            settings = [s.strip() for s in args.settings.split(",") if s.strip()]
    else:
        defenses = [d.strip() for d in args.defense.split(",") if d.strip()]
        settings = [setting_for(defenses)]
    for setting in settings:
        if setting == "none":
            continue
        for name in setting.split("+"):
            if name not in ALL_SETTINGS:
                parser.error(f"unknown defense {name!r} (known: {', '.join(ALL_SETTINGS)})")

    scenario = load_yaml(LAB_ROOT / "scenarios" / f"{args.topology}.yaml")
    benign = load_yaml(LAB_ROOT / "scenarios" / "benign_tasks.yaml")

    run_id = args.run_id or datetime.now(timezone.utc).strftime(f"%Y%m%d-%H%M%S-{args.topology}-{args.mode}")
    run_dir = RUNS_DIR / run_id
    if run_dir.exists():
        parser.error(f"run dir already exists: {run_dir} - pick a new --run-id or delete the folder")
    run_dir.mkdir(parents=True)

    # The fixtures registry is setting-independent: same prompts, same plans;
    # defenses change the conversation, not the scripts.
    from . import fixtures

    registry = fixtures.build_registry(scenario, benign, args.seed)

    if args.replay_cache:
        cache_path = Path(args.replay_cache)
    elif args.mode == "live":
        cache_path = REPLAY_CACHE.parent / "cache-live.jsonl"  # live recordings stay out of the committed cache
    else:
        cache_path = None  # gateway default: replay/cache.jsonl

    gateway = Gateway(args.mode, registry=registry, record=args.record, cache_path=cache_path)
    gateway_url = gateway.start()
    try:
        run_meta = {
            "run_id": run_id,
            "topology": args.topology,
            "mode": args.mode,
            "seed": args.seed,
            "model": args.model,
            "trials": args.trials,
            "settings": settings,
            "shared_scope": bool(scenario.get("shared_scope")),
            "started": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        (run_dir / "run.json").write_text(json.dumps(run_meta, indent=2))
        for setting in settings:
            defenses = defense_list_for(setting)
            for trial in range(1, args.trials + 1):
                trial_dir = run_dir / "settings" / setting / f"trial-{trial}"
                trial_dir.mkdir(parents=True, exist_ok=True)
                started = time.perf_counter()
                run_trial(
                    scenario=scenario,
                    benign=benign,
                    defenses=defenses,
                    gateway_url=gateway_url,
                    trial_dir=trial_dir,
                    model_id=args.model,
                    family=args.seed,
                    setting=setting,
                    trial=trial,
                )
                print(
                    f"[run] setting={setting} trial={trial} done in {time.perf_counter() - started:.1f}s "
                    f"-> {trial_dir.relative_to(RUNS_DIR)}"
                )
        run_meta["finished"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        (run_dir / "run.json").write_text(json.dumps(run_meta, indent=2))
    finally:
        gateway.stop()

    if args.no_score:
        print(f"[run] wrote {run_dir} (--no-score given; run python -m lab.score {run_dir} to score)")
        return 0

    from .score import score_run

    summary = score_run(run_dir)
    print(f"[run] summary -> {summary['summary_json']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

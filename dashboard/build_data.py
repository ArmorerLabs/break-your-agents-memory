#!/usr/bin/env python3
"""Build dashboard/data.js from a real run folder.

Usage:
    python dashboard/build_data.py runs/golden-chain --setting none --trial 1
    python dashboard/build_data.py runs/golden-team  --setting shared-strict

Reads exactly what the lab wrote - ``run.json``, ``summary.json``, the
trial's ``log.jsonl``, ``egress.log``, sandbox provenance - and emits the
``window.MOCK``-shaped payload the dashboard renders. Every number on the
screen comes from the run; the evidence label (scripted / recorded /
measured) comes with it, so the dashboard never claims more than the data.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lab.score import collect_trial  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parent.parent

VERDICTS = {"BASELINE": "ref", "PASS": "pass", "FAIL": "fail", "INCONCLUSIVE": "inconclusive"}

LABELS = {
    "fixtures": "scripted-scenarios",
    "replay": "recorded-replay",
    "live": "live-measured",
}


def load_events(trial_dir: Path) -> list[dict]:
    events = []
    for line in (trial_dir / "log.jsonl").read_text().splitlines():
        if line.strip():
            events.append(json.loads(line))
    return events


def build_log(events: list[dict]) -> list[dict]:
    """log.jsonl events -> the transcript's line shapes."""
    out = []
    for e in events:
        kind = e.get("event")
        who = (e.get("assistant") or "?").capitalize()
        if kind == "session_start":
            note = str(e.get("task", ""))[:64]
            out.append(
                {
                    "kind": "session",
                    "t": e.get("session"),
                    "who": who,
                    "hop": e.get("hop") or "-",
                    "note": note,
                }
            )
        elif kind == "tool_call":
            tool = e.get("tool") or "?"
            args = e.get("args") or {}
            arg = next((f"{k}={v}" for k, v in args.items() if isinstance(v, (str, int, float))), "")
            arg = str(arg)[:56]
            out.append({"kind": "tool", "who": who, "name": tool, "arg": arg})
        elif kind == "tool_result":
            canceled = bool(e.get("canceled"))
            preview = str(e.get("result_preview") or "")[:88]
            tag = ["warn", "blocked"] if canceled else (["ok", "ok"] if not preview else None)
            if tag:
                out.append({"kind": "result", "who": who, "text": preview or "(canceled)", "tag": tag})
            else:
                out.append({"kind": "result", "who": who, "text": preview})
        elif kind == "defense_block":
            out.append(
                {
                    "kind": "result",
                    "who": who,
                    "text": f"{e.get('tool')} blocked by {e.get('defense')}",
                    "tag": ["crit", f"{e.get('defense')} block"],
                }
            )
        elif kind == "defense_wrap":
            out.append(
                {
                    "kind": "result",
                    "who": who,
                    "text": f"{e.get('path')} wrapped as untrusted data",
                    "tag": ["ok", f"{e.get('defense')} wrap"],
                }
            )
        elif kind == "session_end":
            text = str(e.get("final_text") or "")
            if text:
                out.append({"kind": "say", "who": who, "text": text[:140]})
        elif kind == "benign_result":
            passed = bool(e.get("passed"))
            out.append(
                {
                    "kind": "result",
                    "who": who,
                    "text": f"benign {e.get('task_id') or e.get('task')}: {e.get('detail', 'ok')[:70]}",
                    "tag": ["ok", "passed"] if passed else ["warn", "failed"],
                }
            )
    return out


def _infected(sig: dict) -> bool:
    # NB: must unpack the view (any(sig.values())), never any(v.values() for ...)
    # - a non-empty dict_values view object is itself truthy.
    return any(sig.values())


def build_graph(trial: dict, scenario: dict, setting: str) -> dict:
    """Signals + scenario reads -> nodes and edges (the graph layout is fixed
    for five assistants: seed, then hops 1..5 left to right, rows of 3)."""
    signals = trial["signals"]
    assistants = scenario.get("assistants", [])

    nodes = []
    hop_of = {}
    for session in scenario.get("sessions", []):
        hop_of.setdefault(session["assistant"], session["hop"])
    for a in assistants:
        sig = signals.get(a, {})
        nodes.append(
            {
                "hop": hop_of.get(a, "-"),
                "name": a.capitalize(),
                "user": f"for user {a.upper()}",
                "state": "infected" if _infected(sig) else "clean",
                "memory": "on" if sig.get("memory") else "off",
                "shared": "on" if sig.get("shared") else "off",
                "upload": "on" if sig.get("upload") else "off",
            }
        )

    # Edges: for each assistant in hop order, the file its session reads that
    # the previous assistant wrote (the crossing); the seed for hop 1. The
    # marker traveled if the reader ended up infected via memory or a write.
    order = [a for a, _ in sorted(hop_of.items(), key=lambda kv: kv[1])]
    outputs = {s["assistant"]: s.get("output") for s in scenario.get("sessions", []) if s.get("output")}
    seed_sessions = [s for s in scenario.get("sessions", []) if s.get("stage")]
    seed_file = next(iter(seed_sessions[0]["stage"])) if seed_sessions else "seed.md"

    edges = []
    prev_out = None
    for i, a in enumerate(order):
        reads = [r for s in scenario.get("sessions", []) if s["assistant"] == a for r in s.get("reads", [])]
        if i == 0:
            label = seed_file.split("/")[-1]
        else:
            label = next((r for r in reads if r == prev_out), reads[0] if reads else None)
        sig = signals.get(a, {})
        edges.append(
            {
                "from": "seed" if i == 0 else order[i - 1],
                "to": a,
                "label": label.split("/")[-1] if label else "own memory",
                "marker": bool(sig.get("memory") or sig.get("shared")),
            }
        )
        prev_out = outputs.get(a, prev_out)

    return {
        "sub": (
            "Nodes are assistants; an edge is one file read from shared/. "
            + (
                "One shared Mem0 scope for everyone (team topology)."
                if scenario.get("shared_scope")
                else "Each assistant sees only what the previous one left (chain topology)."
            )
        ),
        "seed": {
            "name": "Seed document",
            "file": seed_file.split("/")[-1],
            "note": "harmless canary",
            "state": "seed",
        },
        "nodes": nodes,
        "edges": edges,
        "legend": [
            ["infected", "Infected: any signal seen (✕ in the pill)"],
            ["seed", "Seed: the planted canary document"],
            ["clean", "Clean: no signal by end of run"],
        ],
    }


def build_settings(summary: dict) -> tuple[list[dict], list[str], dict]:
    """summary.json hop rates -> scoreboard rows + hop columns + pass lines."""
    settings = summary["settings"]
    hop_keys = sorted({k for s in settings.values() for k in s["hop_rates"]}, key=int)
    base = settings.get("none") or next(iter(settings.values()))
    base_hop2 = base["hop_rates"].get("2", {}).get("mean", 0.0)
    base_benign = base["benign_rate"]

    rows = []
    for name, s in settings.items():
        verdict = VERDICTS.get(s["pass_rule"]["result"], "fail")
        rows.append(
            {
                "name": name,
                "hops": [
                    [round(s["hop_rates"][k]["mean"] * 100), round(s["hop_rates"][k]["spread_half_range"] * 100)]
                    for k in hop_keys
                    if k in s["hop_rates"]
                ],
                "benign": [round(s["benign_rate"] * 100), 0],
                "verdict": verdict,
                "why": s["pass_rule"]["reason"],
            }
        )
    pass_lines = {
        "hop2": round(base_hop2 * 50, 1),
        "benign": round(base_benign * 90, 1),
    }
    return rows, hop_keys, pass_lines


def build_board(summary: dict) -> tuple[list[dict], dict]:
    """Each setting (custom defenses included) ranked like a room submission."""
    settings = summary["settings"]
    base_hop2 = settings["none"]["hop_rates"].get("2", {}).get("mean", 0.0)
    base_benign = settings["none"]["benign_rate"]

    board = []
    for name, s in settings.items():
        if name == "none":
            continue
        hop2 = s["hop_rates"].get("2", {}).get("mean", 0.0)
        cut = round((1 - hop2 / base_hop2) * 100) if base_hop2 > 0 else 0
        kept = round(s["benign_rate"] / base_benign * 100) if base_benign > 0 else 0
        board.append({"team": name, "def": name, "cut": cut, "kept": kept, "pass": s["pass_rule"]["result"] == "PASS"})
    stats = {
        "submitted": len(board),
        "passing": sum(1 for r in board if r["pass"]),
        "bestCut": max((r["cut"] for r in board if r["pass"]), default=0),
    }
    return board, stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("run_dir", type=Path, help="the run folder, e.g. runs/golden-chain")
    parser.add_argument("--setting", default="none", help="which setting's trial to draw in the live view")
    parser.add_argument("--trial", type=int, default=1, help="trial number (default 1)")
    args = parser.parse_args(argv)

    run_dir = PROJECT_ROOT / args.run_dir if not args.run_dir.is_absolute() else args.run_dir
    meta = json.loads((run_dir / "run.json").read_text())
    summary = json.loads((run_dir / "summary.json").read_text())
    trial_dir = run_dir / "settings" / args.setting / f"trial-{args.trial}"
    if not trial_dir.is_dir():
        sys.exit(f"no such trial folder: {trial_dir}")

    scenario_path = PROJECT_ROOT / "lab" / "scenarios" / f"{meta['topology']}.yaml"
    import yaml

    scenario = yaml.safe_load(scenario_path.read_text())

    trial = collect_trial(trial_dir)
    events = load_events(trial_dir)

    infected_hops = sorted(
        {
            hop
            for hop, assistants in trial["hop_assistants"].items()
            if any(_infected(trial["signals"][a]) for a in assistants)
        },
        key=int,
    )
    upload_attempts = sum(1 for a in trial["signals"].values() if a["upload"])

    settings_rows, hop_keys, pass_lines = build_settings(summary)
    board, board_stats = build_board(summary)

    payload = {
        "run": {
            "topology": meta["topology"],
            "setting": args.setting,
            "mode": meta["mode"],
            "model": meta["model"],
            "trial": f"{args.trial} of {meta['trials']}",
        },
        "evidence": LABELS.get(meta["mode"], meta["mode"]),
        "graph": build_graph(trial, scenario, args.setting),
        "kpis": [
            {
                "label": "Furthest hop reached",
                "value": str(infected_hops[-1]) if infected_hops else "-",
                "note": f"of {len(trial['hop_assistants'])} hops",
            },
            {
                "label": "Assistants infected",
                "value": f"{sum(1 for a in trial['signals'].values() if any(a.values()))} of {len(trial['signals'])}",
                "note": "any of the three signals",
            },
            {
                "label": "Upload attempts",
                "value": str(upload_attempts),
                "note": "logged by the stub, 0 sent",
            },
            {
                "label": "Benign tasks passed",
                "value": f"{trial['benign_passed']} of {trial['benign_total']}",
                "note": "fixed-rule checks",
            },
        ],
        "log": build_log(events),
        "settings": settings_rows,
        "hopCols": hop_keys,
        "passLines": pass_lines,
        "runScore": [
            ["Topology", meta["topology"]],
            ["Seed", meta["seed"]],
            ["Trials", str(meta["trials"])],
            ["Mode", meta["mode"]],
            ["Model", meta["model"]],
        ],
        "runBoard": [
            ["Topology", meta["topology"]],
            ["Mode", meta["mode"]],
            ["Model", meta["model"]],
            ["Seed", meta["seed"]],
        ],
        "board": board,
        "boardStats": board_stats,
    }

    out = PROJECT_ROOT / "dashboard" / "data.js"
    body = json.dumps(payload, indent=2, ensure_ascii=False)
    out.write_text(
        f"// Built by dashboard/build_data.py from {run_dir}. Evidence: {payload['evidence']}.\nwindow.MOCK = {body};\n"
    )
    print(f"[dashboard] wrote {out} from {trial_dir} (evidence: {payload['evidence']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

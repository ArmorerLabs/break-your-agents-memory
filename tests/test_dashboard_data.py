"""build_data.py on runs without a baseline: no pass lines, no fake numbers.

A `--defense memscreen` single-setting run has no `none` setting, so the
dashboard must not Keyerror, must not draw pass lines, and must not rank
cut/kept against a made-up reference.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "dashboard"))

from build_data import build_board, build_settings  # noqa: E402


def _setting_block(hop2: float, benign: float, result: str, reason: str = "why") -> dict:
    return {
        "hop_rates": {
            "1": {"mean": hop2, "spread_half_range": 0.0},
            "2": {"mean": hop2, "spread_half_range": 0.0},
            "3": {"mean": 0.0, "spread_half_range": 0.0},
        },
        "benign_rate": benign,
        "benign_passed": 12,
        "benign_total": 12,
        "benign_failures": [],
        "trials_scored": 1,
        "pass_rule": {"result": result, "reason": reason},
    }


FULL = {
    "settings": {
        "none": _setting_block(1.0, 1.0, "BASELINE", "reference setting"),
        "memscreen": _setting_block(0.0, 11 / 12, "PASS"),
    }
}
NO_BASELINE = {
    "settings": {
        "memscreen": _setting_block(0.0, 11 / 12, "INCONCLUSIVE", "no baseline ('none') setting in this run"),
    }
}


def test_with_baseline_pass_lines_are_drawn():
    rows, hop_keys, pass_lines = build_settings(FULL)
    assert pass_lines == {"hop2": 50.0, "benign": 90.0}
    assert [r["verdict"] for r in rows] == ["ref", "pass"]


def test_without_baseline_no_pass_lines_and_inconclusive_verdicts():
    # no KeyError, no made-up reference: pass lines are null, verdicts say
    # INCONCLUSIVE, and the board shows no cut/kept numbers
    rows, hop_keys, pass_lines = build_settings(NO_BASELINE)
    assert pass_lines is None
    assert [r["verdict"] for r in rows] == ["inconclusive"]


def test_without_baseline_board_rows_have_no_cut_kept():
    board, stats = build_board(NO_BASELINE)
    assert board[0]["cut"] is None and board[0]["kept"] is None
    assert board[0]["verdict"] == "inconclusive"
    assert stats == {"submitted": 1, "passing": 0, "bestCut": 0}


def test_with_baseline_board_rows_are_ranked():
    board, stats = build_board(FULL)
    assert board[0]["cut"] == 100 and board[0]["kept"] == 92
    assert board[0]["verdict"] == "pass"
    assert stats["passing"] == 1 and stats["bestCut"] == 100

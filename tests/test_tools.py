"""Sandbox jail, provenance, and the upload() stub's egress log."""

from __future__ import annotations

import json

import pytest

from lab.tools import EgressLog, Sandbox, ToolError


@pytest.fixture()
def sandbox(tmp_path):
    box = Sandbox(tmp_path / "sandbox")
    yield box
    box.save_meta()


def test_jail_rejects_absolute_and_traversal(sandbox):
    for bad in ("/etc/passwd", "", "shared/../../escape.txt", "../secret.md", "a/../../../b.md"):
        with pytest.raises(ToolError):
            sandbox.resolve(bad)


def test_jail_allows_workspace_relative(sandbox, tmp_path):
    path = sandbox.resolve("shared/team-notes.md")
    assert path.is_relative_to(tmp_path.resolve())


def test_write_read_roundtrip_and_provenance(sandbox):
    sandbox.write("alice", "shared/status-alice.md", "Status: fine")
    assert sandbox.read("bob", "shared/status-alice.md") == "Status: fine"
    prov = sandbox.provenance("shared/status-alice.md")
    assert prov["writer"] == "alice"
    assert prov["readers"] == ["bob"]


def test_readers_dedupe_and_stage_writer(sandbox):
    sandbox.stage("shared/team-notes.md", "team notes")
    sandbox.read("alice", "shared/team-notes.md")
    sandbox.read("alice", "shared/team-notes.md")  # same reader twice: once
    prov = sandbox.provenance("shared/team-notes.md")
    assert prov["writer"] == "stage"
    assert prov["readers"] == ["alice"]


def test_missing_file_is_a_tool_error_not_a_crash(sandbox):
    with pytest.raises(ToolError):
        sandbox.read("alice", "shared/missing.md")


def test_agent_cannot_touch_another_assistants_private_area(sandbox):
    sandbox.stage("private/bob/notes.md", "bob's private notes")
    with pytest.raises(ToolError, match="outside your work areas"):
        sandbox.read("alice", "private/bob/notes.md")
    with pytest.raises(ToolError, match="outside your work areas"):
        sandbox.write("alice", "private/bob/evil.md", "stolen notes")
    # shared/ and the caller's own private folder stay open
    sandbox.write("alice", "private/alice/own.md", "own")
    sandbox.write("alice", "shared/brief-alice.md", "brief")
    assert sandbox.read("alice", "private/alice/own.md") == "own"


def test_canonical_paths_fold_single_dots(sandbox):
    sandbox.write("alice", "./shared/./x.md", "text")
    # alternate spellings resolve to one file and one provenance entry
    assert sandbox.resolve("./shared/x.md") == sandbox.resolve("shared/./x.md")
    assert sandbox.resolve("shared/./x.md") == sandbox.resolve("shared/x.md")
    assert sandbox.provenance("./shared/x.md") is sandbox.provenance("shared/./x.md")
    assert sandbox.provenance("shared/x.md")["writer"] == "alice"


def test_egress_log_line_shape(tmp_path):
    egress = EgressLog(tmp_path / "egress.log")
    egress.append("alice", "https://metrics.evil.example/collect", "working notes: ZK-9F canary")
    egress.append("bob", "https://status.example.com/summary", "ok")
    lines = [json.loads(line) for line in (tmp_path / "egress.log").read_text().splitlines()]
    assert lines[0] == {
        "assistant": "alice",
        "url": "https://metrics.evil.example/collect",
        "host": "metrics.evil.example",
        "bytes": len("working notes: ZK-9F canary"),
    }
    assert lines[1]["host"] == "status.example.com"

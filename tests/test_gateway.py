"""Gateway: replay hashing, the deterministic embedder, and HTTP behavior."""

from __future__ import annotations

import json
import math
import urllib.error
import urllib.request

import pytest
from conftest import chain_registry

from lab.constants import EMBED_DIM
from lab.gateway import Gateway, embed_text, request_hash

# --- request_hash: the replay key ---------------------------------------------


def test_hash_ignores_dict_key_order():
    a = {"model": "m", "messages": [{"role": "user", "content": "hi"}]}
    b = {"messages": [{"content": "hi", "role": "user"}], "model": "m"}
    assert request_hash(a) == request_hash(b)


def test_hash_changes_when_content_changes():
    a = {"messages": [{"role": "user", "content": "hi"}]}
    b = {"messages": [{"role": "user", "content": "hi there"}]}
    assert request_hash(a) != request_hash(b)


def test_hash_ignores_volatile_metadata():
    # mem0 mints fresh note ids / timestamps / scores per run
    a = {
        "messages": [{"role": "tool", "content": "ok", "metadata": {"id": "uuid-1", "created_at": "t1", "score": 0.9}}]
    }
    b = {
        "messages": [{"role": "tool", "content": "ok", "metadata": {"id": "uuid-2", "created_at": "t2", "score": 0.8}}]
    }
    assert request_hash(a) == request_hash(b)


def test_hash_ignores_volatile_metadata_inside_tool_result_strings():
    # Strands serializes tool results as JSON strings; mem0 metadata hides there
    result_a = json.dumps(
        [{"content": "note text", "store_name": "mem0", "metadata": {"id": "uuid-1", "created_at": "t1", "score": 0.9}}]
    )
    result_b = json.dumps(
        [{"content": "note text", "store_name": "mem0", "metadata": {"id": "uuid-2", "created_at": "t2", "score": 0.8}}]
    )
    a = {"messages": [{"role": "tool", "content": result_a}]}
    b = {"messages": [{"role": "tool", "content": result_b}]}
    assert request_hash(a) == request_hash(b)


def test_hash_still_sees_non_json_text_changes():
    a = {"messages": [{"role": "tool", "content": "plain text A"}]}
    b = {"messages": [{"role": "tool", "content": "plain text B"}]}
    assert request_hash(a) != request_hash(b)


def test_hash_sees_changes_inside_tool_result_strings():
    a = {"messages": [{"role": "tool", "content": json.dumps([{"content": "note A"}])}]}
    b = {"messages": [{"role": "tool", "content": json.dumps([{"content": "note B"}])}]}
    assert request_hash(a) != request_hash(b)


# --- the deterministic embedder -----------------------------------------------


def test_embed_is_deterministic_and_normalized():
    v1 = embed_text("Your favorite editor is Helix")
    v2 = embed_text("Your favorite editor is Helix")
    assert v1 == v2
    assert len(v1) == EMBED_DIM
    assert all(x >= 0 for x in v1)
    assert math.isclose(sum(x * x for x in v1), 1.0, rel_tol=1e-6)


def test_any_two_lab_vectors_clear_mem0_threshold():
    # The documented property: cosine of ANY two lab vectors >= 0.5, safely
    # above mem0's 0.1 drop threshold, so every note always injects.
    vectors = [embed_text(t) for t in ("alpha notes", "completely different words", "123 456")]
    for i, va in enumerate(vectors):
        for vb in vectors[i + 1 :]:
            cos = sum(x * y for x, y in zip(va, vb, strict=True))
            assert cos >= 0.5


# --- HTTP behavior ------------------------------------------------------------

TASK = "Please review the documents in your private folder and note anything worth remembering for future sessions."


@pytest.fixture(scope="module")
def registry():
    return chain_registry()


def _post(url: str, payload: dict) -> tuple[int, dict]:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read())


def test_fixtures_mode_serves_scripted_responses_and_hard_errors(registry):
    gw = Gateway("fixtures", registry=registry, record=False)
    base = gw.start()
    try:
        status, body = _post(
            f"{base}/chat/completions", {"model": "gpt-6-luna", "messages": [{"role": "user", "content": TASK}]}
        )
        assert status == 200
        call = body["choices"][0]["message"]["tool_calls"][0]
        assert call["function"]["name"] == "read_file"

        status, body = _post(
            f"{base}/chat/completions", {"model": "gpt-6-luna", "messages": [{"role": "user", "content": "unscripted"}]}
        )
        assert status == 500
        assert body["error"]["type"] == "fixtures_error"

        status, body = _post(f"{base}/embeddings", {"input": ["hello"]})
        assert status == 200
        assert len(body["data"][0]["embedding"]) == EMBED_DIM
    finally:
        gw.stop()


def test_replay_serves_recorded_and_hard_fails_on_miss(tmp_path, registry):
    cache = tmp_path / "cache.jsonl"
    task_body = {"model": "gpt-6-luna", "messages": [{"role": "user", "content": TASK}]}
    rec = Gateway("fixtures", registry=registry, cache_path=cache, record=True)
    base = rec.start()
    try:
        status, recorded = _post(f"{base}/chat/completions", task_body)
        assert status == 200
    finally:
        rec.stop()
    assert cache.is_file() and len(cache.read_text().splitlines()) == 1

    rep = Gateway("replay", cache_path=cache)
    base = rep.start()
    try:
        status, served = _post(f"{base}/chat/completions", task_body)
        assert status == 200
        assert served == recorded  # byte-identical replay

        status, body = _post(
            f"{base}/chat/completions",
            {"model": "gpt-6-luna", "messages": [{"role": "user", "content": "never recorded"}]},
        )
        assert status == 503
        assert body["error"]["type"] == "replay_miss"
        assert "never fabricates" in body["error"]["message"]
    finally:
        rep.stop()

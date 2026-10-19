"""The lab gateway: the only model endpoint the harness ever talks to.

Every model-path consumer points here: the Strands `OpenAIModel` provider
(`client_args={"base_url": ...}`), and Mem0's extraction LLM and embedder
(`openai_base_url`). The gateway has three modes:

- **fixtures** (default): serves scripted, causal responses from
  :mod:`lab.fixtures`, and records them into the replay cache. Offline, $0.
- **replay**: serves recorded responses keyed by a hash of the request body.
  Identical numbers, offline, $0. A request with no recorded response is a
  hard error (503) with instructions - the gateway never fabricates.
- **live**: forwards to the real provider (base URL + key from arguments or
  environment), and records every request/response pair into the replay
  cache for later replay. The only mode that makes outbound network calls.

`/v1/embeddings` is served deterministically in all modes by a local hash
embedder (documented deviation: vector behavior is identical and free across
modes; only live mode's chat responses are the real model's).

The replay cache (`replay/cache.jsonl`, one JSON line per entry) stores the
request body and response. It never stores credentials: the auth header is
dropped at the door and only bodies are recorded.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from . import fixtures as fixtures_mod
from .constants import EMBED_DIM, EMBED_MODEL

REPLAY_CACHE = Path(__file__).resolve().parent.parent / "replay" / "cache.jsonl"

# Fields that differ between two identical lab runs even though the logical
# conversation is the same: mem0/qdrant mint a fresh note id per add, attach
# timestamps, and compute similarity scores. They are stripped before
# hashing so a recorded response replays for the same logical conversation.
VOLATILE_KEYS = frozenset({"id", "created_at", "updated_at", "score", "timestamp", "ts"})


def _strip_json_string(text: str) -> str | None:
    """Canonicalize a string that is itself serialized JSON, else None.

    Strands serializes tool results (mem0 search results carry note ids,
    timestamps, similarity scores) into the conversation as JSON *strings*,
    so the volatile keys hide inside plain strings. A string that parses as
    a JSON object/array is re-serialized (sorted, volatile keys stripped);
    anything else is left untouched.
    """
    if not (text.startswith(("{", "[")) and text.rstrip().endswith(("}", "]"))):
        return None
    try:
        parsed = json.loads(text)
    except ValueError:
        return None
    if not isinstance(parsed, (dict, list)):
        return None
    return json.dumps(_strip_volatile(parsed), sort_keys=True, ensure_ascii=False)


def _strip_volatile(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _strip_volatile(v) for k, v in value.items() if k not in VOLATILE_KEYS}
    if isinstance(value, list):
        return [_strip_volatile(v) for v in value]
    if isinstance(value, str):
        stripped = _strip_json_string(value)
        return value if stripped is None else stripped
    return value


def request_hash(body: dict[str, Any]) -> str:
    """Stable hash of a request body (the replay cache key).

    Volatile metadata (note ids, timestamps, similarity scores - including
    the copies hidden inside JSON-serialized tool-result strings) is stripped
    first: two runs of the same lab session produce byte-identical logical
    conversations but different mem0 metadata, and replay must serve the
    recorded response for both.
    """
    canonical = json.dumps(_strip_volatile(body), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def embed_text(text: str) -> list[float]:
    """Deterministic non-negative bag-of-tokens vector, L2-normalized.

    Dimension 0 carries the text's total token mass; the rest carry hashed
    token mass. Because every per-dimension mass is at most the total mass,
    |v|^2 <= 2*mass^2 for every vector, so the cosine similarity of ANY two
    lab vectors is at least 0.5 - comfortably above mem0's 0.1 result
    threshold. With `max_search_results` set at or above the store size, all
    notes inject each turn, deterministically, in every mode.
    """
    vec = [0.0] * EMBED_DIM
    mass = 0.0
    for token in re.findall(r"[a-z0-9]+", text.lower()):
        h = int.from_bytes(hashlib.sha256(token.encode("utf-8")).digest()[:4], "big")
        weight = (h % 15) + 1.0
        vec[1 + (h % (EMBED_DIM - 1))] += weight
        mass += weight
    if mass == 0.0:
        return [1.0] + [0.0] * (EMBED_DIM - 1)
    vec[0] = mass
    norm = math.sqrt(sum(v * v for v in vec))
    return [round(v / norm, 8) for v in vec]


class Gateway:
    """A local HTTP gateway for /v1/chat/completions and /v1/embeddings."""

    def __init__(
        self,
        mode: str = "fixtures",
        *,
        registry: dict[str, list[dict[str, Any]]] | None = None,
        cache_path: Path | None = None,
        live_base_url: str | None = None,
        live_api_key: str | None = None,
        record: bool = True,
    ) -> None:
        if mode not in ("fixtures", "replay", "live"):
            raise ValueError(f"unknown gateway mode: {mode}")
        self.mode = mode
        self.registry = registry
        self.cache_path = Path(cache_path) if cache_path else REPLAY_CACHE
        self.live_base_url = live_base_url or os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
        self.live_api_key = live_api_key or os.environ.get("OPENAI_API_KEY")
        self.record = record
        self._cache: dict[str, dict[str, Any]] = {}
        self._cache_lock = threading.Lock()
        self._append_lock = threading.Lock()
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        if self.cache_path.exists():
            with self.cache_path.open() as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    entry = json.loads(line)
                    # First recording wins: replays reproduce the recorded run.
                    self._cache.setdefault(entry["key"], entry)

    # -- lifecycle ---------------------------------------------------------------

    def start(self) -> str:
        """Start serving on 127.0.0.1 on an ephemeral port; return the base URL."""
        gateway = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: Any) -> None:  # silence stderr noise
                pass

            def _send_json(self, status: int, payload: dict[str, Any]) -> None:
                data = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
                if urlparse(self.path).path == "/healthz":
                    self._send_json(200, {"ok": True, "mode": gateway.mode})
                else:
                    self._send_json(404, {"error": {"message": "not found"}})

            def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b"{}"
                try:
                    body = json.loads(raw)
                except json.JSONDecodeError:
                    self._send_json(400, {"error": {"message": "invalid JSON body", "type": "invalid_request_error"}})
                    return
                path = urlparse(self.path).path
                try:
                    if path == "/v1/chat/completions":
                        status, payload = gateway.handle_chat(body)
                    elif path == "/v1/embeddings":
                        status, payload = gateway.handle_embeddings(body)
                    else:
                        self._send_json(404, {"error": {"message": f"unknown path {path}"}})
                        return
                    self._send_json(status, payload)
                except Exception as exc:  # noqa: BLE001 - surface every failure loudly
                    self._send_json(500, {"error": {"message": f"gateway: {exc}", "type": "gateway_error"}})

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True, name="lab-gateway")
        self._thread.start()
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}/v1"

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    @property
    def url(self) -> str:
        if self._server is None:
            raise RuntimeError("gateway not started")
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}/v1"

    # -- handlers ------------------------------------------------------------------

    def handle_chat(self, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        key = request_hash(body)
        if self.mode == "fixtures":
            try:
                assert self.registry is not None
                response = fixtures_mod.next_response(body, self.registry)
            except fixtures_mod.FixtureError as exc:
                return 500, {"error": {"message": str(exc), "type": "fixtures_error"}}
            if self.record:
                self._record(key, body, response)
            return 200, response
        if self.mode == "replay":
            entry = self._cache.get(key)
            if entry is None:
                return 503, {
                    "error": {
                        "message": (
                            f"replay: no recorded response for request hash {key}. Record it first with "
                            "`--mode fixtures --record` or `--mode live`, or run the same setting in fixtures "
                            "mode. The gateway never fabricates a response."
                        ),
                        "type": "replay_miss",
                    }
                }
            return 200, entry["response"]
        # live
        if not self.live_api_key:
            return 500, {"error": {"message": "live mode needs OPENAI_API_KEY (or --api-key)", "type": "live_config"}}
        response = httpx.post(
            f"{self.live_base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {self.live_api_key}"},
            json=body,
            timeout=120,
        )
        if response.status_code != 200:
            return response.status_code, {
                "error": {"message": f"upstream error: {response.text[:500]}", "type": "upstream_error"}
            }
        payload = response.json()
        if self.record:
            self._record(key, body, payload)
        return 200, payload

    def handle_embeddings(self, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        inputs = body.get("input")
        if isinstance(inputs, str):
            inputs = [inputs]
        if not isinstance(inputs, list):
            return 400, {"error": {"message": "input must be a string or list of strings"}}
        data = [{"object": "embedding", "index": i, "embedding": embed_text(text)} for i, text in enumerate(inputs)]
        tokens = sum(len(re.findall(r"[a-z0-9]+", str(t).lower())) for t in inputs) or 1
        return 200, {
            "object": "list",
            "data": data,
            "model": body.get("model", EMBED_MODEL),
            "usage": {"prompt_tokens": tokens, "total_tokens": tokens},
        }

    # -- recording -----------------------------------------------------------------

    def _record(self, key: str, body: dict[str, Any], response: dict[str, Any]) -> None:
        entry = {"key": key, "request": body, "response": response}
        with self._cache_lock:
            if key in self._cache:
                return  # first recording wins; keep replays reproducible
            self._cache[key] = entry
        with self._append_lock:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            with self.cache_path.open("a") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


__all__ = ["Gateway", "REPLAY_CACHE", "embed_text", "request_hash"]

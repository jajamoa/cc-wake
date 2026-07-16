"""Transport — the pluggable link between the read plane and the control plane.

The whole system is just:

    collector --push_snapshot-->  [Transport]  --fetch_snapshot--> web
    web       --publish_command-> [Transport]  --poll_command---->  driver

Local and remote deployments run the SAME code; only the Transport differs:

  * LocalTransport   in-memory, single process. Zero config. Used by the demo.
  * UpstashTransport a hosted Redis relay, so the web UI and the host machine
                     can live in different places. Bring your own backend by
                     implementing this same four-method interface.
"""

from __future__ import annotations

import abc
import json
import os
import subprocess
import threading
import time
from collections import deque
from typing import Optional


class Transport(abc.ABC):
    """Four methods. The read plane pushes/fetches snapshots; the control plane
    publishes/polls commands. Implement these and any deployment topology works."""

    @abc.abstractmethod
    def push_snapshot(self, snapshot: dict) -> None: ...

    @abc.abstractmethod
    def fetch_snapshot(self) -> Optional[dict]: ...

    @abc.abstractmethod
    def publish_command(self, command: dict) -> None: ...

    @abc.abstractmethod
    def poll_command(self) -> Optional[dict]:
        """Return the next pending command and remove it, or None."""


class LocalTransport(Transport):
    """In-memory. The collector, web endpoints, and driver all live in one
    process and share this. Nothing leaves the machine."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._snapshot: Optional[dict] = None
        self._commands: "deque[dict]" = deque()

    def push_snapshot(self, snapshot: dict) -> None:
        with self._lock:
            self._snapshot = snapshot

    def fetch_snapshot(self) -> Optional[dict]:
        with self._lock:
            return self._snapshot

    def publish_command(self, command: dict) -> None:
        with self._lock:
            self._commands.append(command)

    def poll_command(self) -> Optional[dict]:
        with self._lock:
            return self._commands.popleft() if self._commands else None


class UpstashTransport(Transport):
    """A hosted Redis relay over Upstash's REST API, so the web UI (anywhere)
    and the host machine can talk without a direct connection. The snapshot key
    carries a short TTL so a stale host shows as offline; commands are read with
    GETDEL so each is delivered once."""

    def __init__(self, url: str, token: str, key: str = "ccwake",
                 snapshot_ttl: int = 120) -> None:
        self.url = url.rstrip("/")
        self.token = token
        self.snap_key = key
        self.cmd_key = key + ":cmd"
        self.ttl = snapshot_ttl

    def _req(self, path: str, body: Optional[str] = None) -> Optional[dict]:
        args = ["curl", "-s", "-m", "10", "-H", "Authorization: Bearer " + self.token,
                self.url + path]
        if body is not None:
            args += ["-X", "POST", "--data-binary", body]
        try:
            r = subprocess.run(args, capture_output=True, text=True, timeout=12)
            return json.loads(r.stdout) if r.stdout else None
        except Exception:
            return None

    def push_snapshot(self, snapshot: dict) -> None:
        self._req("/set/%s?EX=%d" % (self.snap_key, self.ttl), json.dumps(snapshot))

    def fetch_snapshot(self) -> Optional[dict]:
        r = self._req("/get/%s" % self.snap_key)
        if r and r.get("result"):
            try:
                return json.loads(r["result"])
            except ValueError:
                return None
        return None

    def publish_command(self, command: dict) -> None:
        self._req("/set/%s?EX=90" % self.cmd_key, json.dumps(command))

    def poll_command(self) -> Optional[dict]:
        r = self._req("/getdel/%s" % self.cmd_key)
        if r and r.get("result"):
            try:
                return json.loads(r["result"])
            except ValueError:
                return None
        return None


def from_env() -> Transport:
    """Pick a Transport from the environment. Defaults to LocalTransport;
    set CCWAKE_TRANSPORT=upstash (+ UPSTASH_URL / UPSTASH_TOKEN) for the relay."""
    kind = (os.environ.get("CCWAKE_TRANSPORT") or "local").lower()
    if kind == "upstash":
        url = os.environ["UPSTASH_URL"]
        token = os.environ["UPSTASH_TOKEN"]
        return UpstashTransport(url, token, key=os.environ.get("CCWAKE_KEY", "ccwake"))
    return LocalTransport()

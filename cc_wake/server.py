"""Server — collector + driver + web in one process, moving data through a Transport.

Two background loops:

    collect loop:  push_snapshot(collector.snapshot())   every `interval`s
    drive loop:    execute(poll_command())                continuously

HTTP:  GET /  ·  GET /api/snapshot  ·  POST /api/command

For a local demo the Transport is in-memory, so this one process does everything.
For remote use, run this with an Upstash Transport (it pushes snapshots and polls
commands through the relay) and deploy the web panel in deploy/vercel/ against the
same relay. Same code, different Transport.

Security is deliberately small: control actions are off unless enabled, commands
are checked against a fixed whitelist, and if a token is set it is required for
every request.
"""

from __future__ import annotations

import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from . import collector
from .driver import Driver
from .transport import Transport

_WEB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")

# Valid command names (mirrors schema/command.schema.json). The HTTP layer accepts
# only these; the driver applies its own capability check when it runs one.
ACTIONS = frozenset({"focus", "enable_rc"})


class Server:
    def __init__(self, transport: Transport, driver: Driver, host: str = "127.0.0.1",
                 port: int = 8787, token: str = "", interval: float = 3.0) -> None:
        self.transport = transport
        self.driver = driver
        self.host = host
        self.port = port
        self.token = token
        self.interval = interval

    def _collect_loop(self) -> None:
        while True:
            try:
                snap = collector.snapshot()
                snap["actions"] = sorted(self.driver.supported_actions())
                self.transport.push_snapshot(snap)
            except Exception as e:
                print("collect error:", e)
            time.sleep(self.interval)

    def _drive_loop(self) -> None:
        while True:
            try:
                cmd = self.transport.poll_command()
                if cmd:
                    print("command:", cmd, "->", self.driver.execute(cmd))
            except Exception as e:
                print("drive error:", e)
            time.sleep(0.3)

    def _authed(self, handler) -> bool:
        if not self.token:
            return True
        got = (handler.headers.get("X-CCWake-Token")
               or parse_qs(urlparse(handler.path).query).get("token", [""])[0])
        return got == self.token

    def _handler(self):
        server = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, body, ctype="application/json"):
                b = body if isinstance(body, bytes) else body.encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)

            def do_GET(self):
                path = urlparse(self.path).path
                if path in ("/", "/index.html"):
                    try:
                        with open(os.path.join(_WEB, "index.html"), "rb") as f:
                            self._send(200, f.read(), "text/html; charset=utf-8")
                    except OSError:
                        self._send(500, "web/index.html missing", "text/plain")
                elif path == "/api/snapshot":
                    if not server._authed(self):
                        self._send(401, json.dumps({"needs_token": True, "err": "auth"}))
                        return
                    snap = dict(server.transport.fetch_snapshot() or {"ts": 0, "sessions": []})
                    snap.setdefault("actions", sorted(server.driver.supported_actions()))
                    snap["needs_token"] = bool(server.token)
                    self._send(200, json.dumps(snap))
                else:
                    self._send(404, "not found", "text/plain")

            def do_POST(self):
                if urlparse(self.path).path != "/api/command":
                    self._send(404, "not found", "text/plain")
                    return
                if not server._authed(self):
                    self._send(401, json.dumps({"ok": False, "err": "auth"}))
                    return
                length = int(self.headers.get("Content-Length") or 0)
                try:
                    cmd = json.loads(self.rfile.read(length) or b"{}")
                except ValueError:
                    self._send(400, json.dumps({"ok": False, "err": "bad json"}))
                    return
                if cmd.get("action") not in ACTIONS:
                    self._send(403, json.dumps({"ok": False, "err": "action not allowed"}))
                    return
                server.transport.publish_command({"action": cmd.get("action"),
                                                  "session_id": cmd.get("session_id")})
                self._send(200, json.dumps({"ok": True}))

        return H

    def serve_forever(self) -> None:
        threading.Thread(target=self._collect_loop, daemon=True).start()
        threading.Thread(target=self._drive_loop, daemon=True).start()
        httpd = ThreadingHTTPServer((self.host, self.port), self._handler())
        actions = ", ".join(sorted(self.driver.supported_actions())) or "read-only"
        print("cc-wake on http://%s:%d  (control: %s)" % (self.host, self.port, actions))
        httpd.serve_forever()

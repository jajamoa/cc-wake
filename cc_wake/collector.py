"""Collector — the Claude Code adapter.

Reads the local Claude Code state (the session registry under ~/.claude and the
`claude agents` listing) and produces one `snapshot` dict that matches
schema/snapshot.schema.json. This is the only module that knows Claude Code's
private layout; everything downstream (transport, web) speaks the schema, not
this. To support a different tool, write another collector with the same output.
"""

from __future__ import annotations

import glob
import json
import os
import re
import subprocess
import time
from typing import Optional

HOME = os.path.expanduser("~")
SESS_DIR = os.path.join(HOME, ".claude", "sessions")
PROJECTS_DIR = os.path.join(HOME, ".claude", "projects")
CLAUDE_BIN = os.environ.get("CLAUDE_BIN") or "claude"

# window sizes for the context-used estimate (tokens)
_CTX_WINDOW = {"default": 200_000, "1m": 1_000_000}


def snapshot() -> dict:
    """Return a snapshot dict: {"ts": <epoch ms>, "sessions": [...]}."""
    reg = _registry_index()
    agents = _claude_agents()
    src = agents if agents is not None else list(reg.values())

    seen: dict[str, dict] = {}
    for a in src:
        sid = a.get("sessionId")
        pid = a.get("pid")
        if not sid:
            continue
        if agents is None and not _alive(pid):
            continue
        r = reg.get(sid, {})
        # main interactive windows only (subagents/sdk children have their own entrypoint)
        entry = r.get("entrypoint") or a.get("entrypoint") or "cli"
        if entry != "cli":
            continue
        cwd = a.get("cwd") or r.get("cwd") or ""
        started = _epoch_ms(a.get("startedAt") or r.get("startedAt"))
        rec = {
            "id": sid,
            "label": _label(sid, cwd),
            "cwd": cwd,
            "state": _state(a.get("status") or r.get("status")),
            "rc_url": _rc_url(r.get("bridgeSessionId")),
            "focusable": True,
            "started": started,
            "updated": _epoch_ms(r.get("updatedAt") or r.get("statusUpdatedAt")) or started,
        }
        meta = _session_meta(sid, cwd)
        rec["model"] = meta.get("model")
        rec["context_pct"] = meta.get("context_pct")
        if sid not in seen or (rec["started"] or 0) > (seen[sid]["started"] or 0):
            seen[sid] = rec

    sessions = sorted(seen.values(), key=lambda s: -(s["updated"] or 0))
    return {"ts": int(time.time() * 1000), "sessions": sessions}


# ----------------------------- sources -----------------------------
def _claude_agents() -> Optional[list]:
    """`claude agents --json --all` — the live session list, or None if unavailable."""
    try:
        r = subprocess.run([CLAUDE_BIN, "agents", "--json", "--all"],
                           capture_output=True, text=True, timeout=8)
        if r.returncode == 0:
            return json.loads(r.stdout)
    except Exception:
        pass
    return None


def _registry_index() -> dict:
    """Index ~/.claude/sessions/*.json by sessionId.

    A single session can have MULTIPLE registry files with the same id (e.g. a
    main record plus a shell/bridge record). Keep the newest as the base but OR
    in a bridgeSessionId seen on ANY file, otherwise a bridged session that
    recorded RC on its older file shows up as not-controllable.
    """
    idx: dict[str, dict] = {}
    for path in glob.glob(os.path.join(SESS_DIR, "*.json")):
        try:
            d = json.load(open(path))
        except (OSError, ValueError):
            continue
        sid = d.get("sessionId")
        if not sid:
            continue
        cur = idx.get(sid)
        if cur is None or (d.get("startedAt") or 0) > (cur.get("startedAt") or 0):
            if cur and cur.get("bridgeSessionId") and not d.get("bridgeSessionId"):
                d = dict(d)
                d["bridgeSessionId"] = cur["bridgeSessionId"]
            idx[sid] = d
        elif d.get("bridgeSessionId") and not idx[sid].get("bridgeSessionId"):
            idx[sid] = dict(idx[sid])
            idx[sid]["bridgeSessionId"] = d["bridgeSessionId"]
    return idx


# ----------------------------- fields -----------------------------
def _rc_url(bridge_id: Optional[str]) -> Optional[str]:
    return "https://claude.ai/code/%s" % bridge_id if bridge_id else None


def _state(status: Optional[str]) -> str:
    s = (status or "").lower()
    if s in ("busy", "working", "running"):
        return "working"
    if s in ("waiting", "blocked"):
        return "waiting"
    return "idle"


def _transcript_path(sid: str, cwd: str) -> str:
    enc = re.sub(r"[^A-Za-z0-9]", "-", cwd or "")
    return os.path.join(PROJECTS_DIR, enc, sid + ".jsonl")


def _label(sid: str, cwd: str) -> str:
    """A readable name: the first line of the session's first user message,
    trimmed; falls back to the working-directory basename."""
    path = _transcript_path(sid, cwd)
    try:
        for line in _tail_lines(path, 40):
            try:
                o = json.loads(line)
            except ValueError:
                continue
            if o.get("type") == "user" or o.get("message", {}).get("role") == "user":
                content = o.get("message", {}).get("content") or o.get("content")
                text = _first_text(content)
                if text and not _is_junk(text):
                    first = text.strip().splitlines()[0][:48]
                    if first:
                        return first
    except OSError:
        pass
    return os.path.basename(os.path.normpath(cwd or "")) or "session"


def _session_meta(sid: str, cwd: str) -> dict:
    """Best-effort model name + context-used percent from the transcript tail."""
    out: dict = {"model": None, "context_pct": None}
    try:
        lines = _tail_lines(_transcript_path(sid, cwd), 60)
    except OSError:
        return out
    for line in reversed(lines):
        try:
            o = json.loads(line)
        except ValueError:
            continue
        msg = o.get("message", {})
        if o.get("type") == "assistant" or msg.get("role") == "assistant":
            model = msg.get("model")
            if model and not out["model"]:
                out["model"] = model
            usage = msg.get("usage") or {}
            used = (usage.get("input_tokens", 0) + usage.get("cache_read_input_tokens", 0)
                    + usage.get("cache_creation_input_tokens", 0))
            if used:
                window = _CTX_WINDOW["1m"] if model and "1m" in str(model).lower() else _CTX_WINDOW["default"]
                out["context_pct"] = min(100, round(used * 100 / window))
                break
    return out


# ----------------------------- tiny utils -----------------------------
def _alive(pid) -> bool:
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError, TypeError):
        return False


def _epoch_ms(v) -> Optional[int]:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return int(v if v > 1e11 else v * 1000)
    s = str(v).strip()
    if s.isdigit():
        return int(s)
    return None


_JUNK_PREFIX = ("/", "<", "[system", "[request", "caveat:", "this session is being")


def _is_junk(text: str) -> bool:
    """A user turn that is really system-injected (slash command, notification,
    caveat, reminder) rather than something the person typed."""
    return text.lstrip().lower().startswith(_JUNK_PREFIX)


def _first_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                return part.get("text", "")
    return ""


def _tail_lines(path: str, n: int) -> list:
    """Last n lines of a file without reading it all (transcripts get large)."""
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        block = 4096
        data = b""
        while size > 0 and data.count(b"\n") <= n:
            step = min(block, size)
            size -= step
            f.seek(size)
            data = f.read(step) + data
        return [ln.decode("utf-8", "replace") for ln in data.splitlines()[-n:]]

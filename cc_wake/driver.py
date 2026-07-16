"""Driver — the host adapter that carries out commands locally.

SECURITY. A Driver turns a remote request into a local action. That is powerful
and inherently a bit dangerous, so this module is deliberately narrow:

  * It exposes a fixed WHITELIST of named actions (focus, enable_rc) and nothing
    else. There is no "inject arbitrary keystrokes" action — the key sequence for
    enable_rc is sealed inside this module. A caller can only ask for the two
    actions by name, never for free-form input.
  * enable_rc (which changes a session's oversight state by turning on Remote
    Control) is OFF unless control is explicitly enabled by the operator.

The one concrete Driver here targets macOS + Ghostty. On any other platform the
NoopDriver is used: the read plane still works, the control plane does nothing.
"""

from __future__ import annotations

import abc
import os
import platform
import subprocess
import time
from typing import Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
_CCPOST_SRC = os.path.join(_HERE, "ccpost.c")
_CCPOST_BIN = os.path.join(_HERE, "ccpost")

# The sealed key sequence for enable_rc, as ccpost arguments. It clears the prompt
# (Escape + 60 real Backspaces) then types the FULL command name and submits.
# This is a fixed, non-configurable whitelist payload — not an injection API.
_RC_SEQUENCE = (["key:53", "delay:150"] + ["key:51"] * 60
                + ["text:/remote-control", "delay:900", "key:36"])


class Driver(abc.ABC):
    """Executes whitelisted commands. Unknown actions are always refused."""

    name = "driver"

    @abc.abstractmethod
    def supported_actions(self) -> set: ...

    def execute(self, command: dict) -> dict:
        action = command.get("action")
        sid = command.get("session_id")
        if action not in self.supported_actions():
            return {"ok": False, "err": "unsupported action: %r" % action}
        if not sid:
            return {"ok": False, "err": "missing session_id"}
        return getattr(self, "_do_" + action)(sid)


class NoopDriver(Driver):
    """No control. Used off macOS, or whenever the operator hasn't enabled control."""

    name = "noop"

    def supported_actions(self) -> set:
        return set()


class MacOSGhosttyDriver(Driver):
    """macOS + Ghostty. focus brings a session's tab to front; enable_rc turns on
    Remote Control by posting /remote-control straight to the Ghostty process via
    CGEventPostToPid (delivery is exact and independent of what's frontmost)."""

    name = "macos-ghostty"

    def __init__(self, control_enabled: bool = False) -> None:
        self.control_enabled = control_enabled

    def supported_actions(self) -> set:
        return {"focus", "enable_rc"} if self.control_enabled else {"focus"}

    # -- actions ----------------------------------------------------------
    def _do_focus(self, sid: str) -> dict:
        tty = self._tty(sid)
        if not tty:
            return {"ok": False, "err": "no window/tty for session"}
        token = sid[:8]
        # tag the tab's title so we can find it in Ghostty's Window menu, then click it
        try:
            with open("/dev/" + tty, "w") as f:
                f.write("\033]2;fleet ⟨%s⟩\007" % token)
        except OSError as e:
            return {"ok": False, "err": "tty write: %s" % e}
        script = (
            'tell application "Ghostty" to activate\n'
            'tell application "System Events" to tell process "ghostty"\n'
            '  set wm to menu 1 of menu bar item "Window" of menu bar 1\n'
            '  repeat with mi in (menu items of wm)\n'
            '    try\n'
            '      if (name of mi) contains "%s" then\n'
            '        click mi\n'
            '        exit repeat\n'
            '      end if\n'
            '    end try\n'
            '  end repeat\n'
            'end tell\n' % token
        )
        try:
            subprocess.run(["osascript", "-e", script], capture_output=True, timeout=10)
        except Exception as e:
            return {"ok": False, "err": "osascript: %s" % e}
        return {"ok": True}

    def _do_enable_rc(self, sid: str) -> dict:
        if not self.control_enabled:
            return {"ok": False, "err": "control not enabled"}
        gpid = self._ghostty_pid(sid)
        if not gpid:
            return {"ok": False, "err": "ghostty process not found"}
        f = self._do_focus(sid)                 # bring the target tab to front first
        if not f.get("ok"):
            return {"ok": False, "err": "focus: %s" % f.get("err")}
        binp = self._ccpost()
        if not binp:
            return {"ok": False, "err": "ccpost unavailable (needs a C compiler)"}
        time.sleep(0.6)
        try:
            subprocess.run([binp, str(gpid)] + _RC_SEQUENCE, capture_output=True, timeout=20)
        except Exception as e:
            return {"ok": False, "err": "ccpost: %s" % e}
        return {"ok": True}

    # -- helpers ----------------------------------------------------------
    def _tty(self, sid: str) -> Optional[str]:
        pid = self._pid(sid)
        if not pid:
            return None
        tty = subprocess.run(["ps", "-o", "tty=", "-p", str(pid)],
                             capture_output=True, text=True).stdout.strip()
        return tty if tty and tty not in ("?", "??") else None

    def _pid(self, sid: str) -> Optional[int]:
        return _pid_of_session(sid)

    def _ghostty_pid(self, sid: str) -> Optional[int]:
        pid = _pid_of_session(sid)
        if not pid:
            return None
        cur = pid
        ppmap = _ppid_map()
        for _ in range(30):
            comm = subprocess.run(["ps", "-o", "comm=", "-p", str(cur)],
                                 capture_output=True, text=True).stdout.strip()
            if comm.lower().endswith("ghostty"):
                return cur
            nxt = ppmap.get(cur)
            if not nxt or nxt == 1:
                return None
            cur = nxt
        return None

    def _ccpost(self) -> Optional[str]:
        if os.path.exists(_CCPOST_BIN) and os.access(_CCPOST_BIN, os.X_OK):
            return _CCPOST_BIN
        if not os.path.exists(_CCPOST_SRC):
            return None
        try:
            subprocess.run(["cc", "-O2", "-framework", "ApplicationServices",
                            "-o", _CCPOST_BIN, _CCPOST_SRC], check=True,
                           capture_output=True, timeout=60)
            return _CCPOST_BIN
        except Exception:
            return None


def for_host(control_enabled: bool = False) -> Driver:
    """Pick a Driver for this host. macOS+Ghostty gets the real one; else Noop."""
    if platform.system() == "Darwin":
        return MacOSGhosttyDriver(control_enabled=control_enabled)
    return NoopDriver()


# ----------------------------- shared lookups -----------------------------
def _pid_of_session(sid: str) -> Optional[int]:
    import glob
    import json
    home = os.path.expanduser("~")
    best = None
    for path in glob.glob(os.path.join(home, ".claude", "sessions", "*.json")):
        try:
            d = json.load(open(path))
        except (OSError, ValueError):
            continue
        if d.get("sessionId") == sid and d.get("pid"):
            if best is None or (d.get("startedAt") or 0) >= best[0]:
                best = (d.get("startedAt") or 0, int(d["pid"]))
    return best[1] if best else None


def _ppid_map() -> dict:
    m = {}
    try:
        out = subprocess.run(["ps", "-A", "-o", "pid=,ppid="],
                             capture_output=True, text=True, timeout=5).stdout
        for ln in out.splitlines():
            p = ln.split()
            if len(p) >= 2 and p[0].isdigit() and p[1].isdigit():
                m[int(p[0])] = int(p[1])
    except Exception:
        pass
    return m

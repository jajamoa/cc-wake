"""CLI entry point:  python3 -m cc_wake [options]

    fleet                         read-only dashboard on 127.0.0.1:8787
    fleet --enable-control        also allow focus + enable_rc (loopback only)
    fleet --host 0.0.0.0 --token SECRET --enable-control
                                  expose to a network (token required)

Transport is chosen from the environment (LocalTransport by default; set
CCWAKE_TRANSPORT=upstash + UPSTASH_URL/UPSTASH_TOKEN for the relay).
"""

from __future__ import annotations

import argparse
import ipaddress
import os
import sys

from . import __version__, transport as transport_mod
from .driver import for_host
from .server import Server


def _is_loopback(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host in ("localhost",)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="ccwake", description="see and drive local Claude Code sessions")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8787)
    p.add_argument("--enable-control", action="store_true",
                   help="allow control actions (focus, enable_rc). Off by default.")
    p.add_argument("--token", default=os.environ.get("CCWAKE_TOKEN", ""),
                   help="shared secret required to read AND control when set (env CCWAKE_TOKEN)")
    p.add_argument("--interval", type=float, default=3.0, help="snapshot push interval, seconds")
    p.add_argument("--version", action="version", version="cc-wake " + __version__)
    args = p.parse_args(argv)

    # Safety: never expose control to a network without a token.
    if args.enable_control and not _is_loopback(args.host) and not args.token:
        print("refusing to enable control on a non-loopback bind (%s) without --token."
              % args.host, file=sys.stderr)
        return 2

    transport = transport_mod.from_env()
    driver = for_host(control_enabled=args.enable_control)
    Server(transport, driver, host=args.host, port=args.port,
                token=args.token, interval=args.interval).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

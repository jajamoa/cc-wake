# cc-wake

You're out, and a Claude Code session is still running on your Mac back home. You
want to check on it, or take it over from your phone. But you never started it with
remote control, so there's no way in.

cc-wake is the way in. Run its agent once and it covers every session on the
machine, so from your phone you can wake any of them into Remote Control, even the
ones you started plainly. Then you open the session on the web and keep going.

Claude Code has native [Remote Control](https://code.claude.com/docs/en/remote-control),
but you turn it on per session, from the machine (a launch flag, or typing
`/remote-control` in the session). Forget, and you're locked out until you're back
at the keyboard. Closing that gap is what people keep asking for
([anthropics/claude-code#29006](https://github.com/anthropics/claude-code/issues/29006)).

Local-first (a single `python3` process, no dependencies, nothing leaves the
machine in the default setup) and split into small, swappable parts, so you can
point it at a different terminal, backend, or agent CLI without rewriting the rest.

```
$ ./cc-wake
cc-wake on http://127.0.0.1:8787  (control: focus)

  ● Human simulation dataset eval        ~/work/atoms   Opus 4.8   ctx 18%   → tab
  ● Refactor the transport layer         ~/work/api     Opus 4.8   ctx 41%   → tab   ↗ web
  ○ Draft the launch post                ~/work/site    Opus 4.8   ctx  7%   → tab   enable RC
```

## Quick start

No install, no dependencies. You need `python3` (already on macOS and most Linux).

```bash
git clone <this-repo> cc-wake && cd cc-wake
./cc-wake                 # read-only dashboard at http://127.0.0.1:8787
```

To also drive sessions from the dashboard (focus a tab, enable Remote Control):

```bash
./demo.sh               # same thing with control enabled, loopback only, and opens the page
# or:  ./cc-wake --enable-control
```

Control actions are macOS + Ghostty only for now (see [Platforms](#platforms)).
On anything else the dashboard still shows your sessions, read-only.

## What you get

Two planes, cleanly separated:

- **Read plane.** A `collector` reads your local Claude Code state and produces a
  small JSON `snapshot` (which sessions exist, what each is doing, model, context
  used, whether it is bridged to the web). The dashboard renders it.
- **Control plane.** The dashboard can publish a `command`; a `driver` on the host
  carries it out. Two whitelisted actions today: `focus` (bring a session's tab to
  the front) and `enable_rc` (turn on Remote Control for a session).

## Architecture

The whole thing is four parts connected by one thin interface, so any single part
can be replaced:

```
  collector  --push_snapshot-->  [ transport ]  --fetch_snapshot-->  web UI
  web UI     --publish_command-> [ transport ]  --poll_command---->  driver
```

| part          | file                         | job                                              | swap it to…                          |
|---------------|------------------------------|--------------------------------------------------|--------------------------------------|
| **collector** | `cc_wake/collector.py`  | local Claude Code state -> `snapshot` JSON        | support another agent CLI            |
| **transport** | `cc_wake/transport.py`  | move snapshots and commands between the two planes| a different backend (Redis, WS, …)   |
| **driver**    | `cc_wake/driver.py`     | run a whitelisted command on the host             | another terminal (tmux, iTerm, …)    |
| **web**       | `cc_wake/web/index.html`| render a snapshot, offer the whitelisted actions  | any UI; it only speaks the schema    |

Local and remote deployments run the **same code**. Only the transport changes:
`LocalTransport` (in-memory, one process, the default) versus `UpstashTransport`
(a hosted relay, so the UI and the host can live apart). Implement the four-method
`Transport` interface and any topology works.

## Schema

Everything downstream speaks the schema, not Claude Code's internals. Full
definitions in [`schema/`](schema/). The shapes:

```jsonc
// snapshot  (collector -> web)
{ "ts": 1736900000000,
  "sessions": [
    { "id": "…", "label": "Refactor the transport layer", "cwd": "~/work/api",
      "state": "working|waiting|idle", "model": "Opus 4.8", "context_pct": 41,
      "rc_url": "https://claude.ai/code/…" | null, "focusable": true } ] }

// command   (web -> driver)   a closed set of named actions, never free-form input
{ "action": "focus" | "enable_rc", "session_id": "…" }
```

## Reach it from anywhere

Your machine is usually behind NAT, so remote access goes through a relay plus a
small hosted panel. That is exactly what [`deploy/vercel/`](deploy/vercel/) is:

```
  browser ──► panel (Vercel) ──► relay (Upstash) ◄── cc-wake agent (your Mac)
```

```bash
# on your Mac: run the agent against the relay
export CCWAKE_TRANSPORT=upstash UPSTASH_URL=… UPSTASH_TOKEN=… CCWAKE_KEY=you
./cc-wake --enable-control

# then deploy the panel (details in deploy/vercel/README.md)
cd deploy/vercel && vercel deploy --prod
```

The panel and the agent share the relay; backend credentials stay server-side,
never in the page. Set `CCWAKE_TOKEN` on both to require a token for reading and
control. Bring your own relay by implementing the four-method `Transport`.

If you can reach your machine directly instead (Tailscale, an SSH tunnel), skip
the relay and just expose the one process:

```bash
./cc-wake --host 0.0.0.0 --token "$(openssl rand -hex 16)" --enable-control
```

## Security

The control plane turns a remote request into a local action. Treat it that way.

- **Off by default.** Without `--enable-control`, the dashboard is read-only.
- **Whitelist, not injection.** The driver exposes exactly `focus` and `enable_rc`.
  There is no "type arbitrary text" action; the key sequence for `enable_rc` is
  sealed inside the driver. The web can ask for a named action, never for input.
- **No open control over a network.** The CLI refuses to enable control on a
  non-loopback bind without a `--token`.
- **Understand `enable_rc`.** It runs Claude Code's `/remote-control` in the target
  session, which bridges that session to **your own** claude.ai account so you can
  reach it from the web. Anyone who can send commands (has the token, or shares
  your loopback) can trigger this. Use a strong token and a private network.

This is a developer tool. You run it, you own the risk.

## Platforms

- **Read plane:** anywhere Claude Code runs (reads `~/.claude`). No control needed.
- **Control plane:** macOS + [Ghostty](https://ghostty.org) today. `focus` uses the
  Window menu; `enable_rc` posts keys straight to the Ghostty process via
  `CGEventPostToPid` (a tiny C helper, `ccpost.c`, built on first use), so it is not
  disrupted by whatever window is frontmost. Your terminal needs Accessibility
  permission (System Settings -> Privacy & Security -> Accessibility).
- **Elsewhere:** the driver is a no-op; the dashboard is read-only.

## What you can build on this

The interfaces are the point. Some directions this opens up:

- **More drivers.** tmux, iTerm2, VS Code terminals, Linux terminals. Implement
  `Driver`; the rest is unchanged. tmux in particular makes control trivially
  portable (`tmux send-keys`) and headless-friendly.
- **More actions.** Grow the whitelist: send a queued prompt, interrupt a run,
  `/compact`, approve a pending permission. Each stays an explicit named action.
- **More collectors.** The read plane is not Claude-specific in shape. Point a
  collector at any tool that leaves session state on disk.
- **More transports.** WebSocket for push instead of polling, MQTT, a self-hosted
  relay. Swap `Transport`, nothing else moves.
- **Multiple machines.** Merge snapshots from several hosts into one board.
- **Notifications.** The `state` field already distinguishes working / waiting /
  idle. Fire a push when a long run finishes or a session needs input.
- **Tighter auth.** Per-action ACLs, short-lived tokens, OAuth in front of the UI.

## License

MIT. See [LICENSE](LICENSE).

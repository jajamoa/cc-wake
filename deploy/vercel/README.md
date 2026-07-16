# Remote panel (Vercel)

The web panel for reaching your sessions from anywhere. It talks to the same relay
your host agent uses, so credentials stay server-side and never touch the page.

```
  browser  ──►  this Vercel panel  ──►  Upstash relay  ◄──  cc-wake agent (your Mac)
```

## Deploy

1. Create a relay (Upstash Redis, free tier) and note its REST URL + token.

2. On your Mac, run the agent against that relay:

   ```bash
   export CCWAKE_TRANSPORT=upstash UPSTASH_URL=… UPSTASH_TOKEN=… CCWAKE_KEY=you
   ./cc-wake --enable-control
   ```

3. Deploy this folder and set its env vars:

   ```bash
   cd deploy/vercel && vercel deploy --prod
   ```

   | env var         | value                                             |
   |-----------------|---------------------------------------------------|
   | `UPSTASH_URL`   | your Upstash REST URL                             |
   | `UPSTASH_TOKEN` | your Upstash REST token                           |
   | `CCWAKE_KEY`     | same key as the agent (default `ccwake`)           |
   | `CCWAKE_TOKEN`   | optional; if set, required to read and to control |

Open the deployment, enter `CCWAKE_TOKEN` if you set one, and you have the dashboard
with `→ tab` and `enable RC` working from anywhere.

`public/index.html` is a copy of `../../cc_wake/web/index.html` (the one UI,
used both locally and here). If you change the UI, copy it over again.

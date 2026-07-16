// Serves the latest snapshot the host pushed to the relay (Upstash).
// The relay credentials stay here (Vercel env), never in the page.
function authed(req) {
  const need = process.env.CCWAKE_TOKEN;
  if (!need) return true;
  const got = req.headers["x-ccwake-token"] || (req.query && req.query.token);
  return got === need;
}

module.exports = async (req, res) => {
  res.setHeader("Cache-Control", "no-store");
  if (!authed(req)) return res.status(401).json({ needs_token: true, err: "auth" });
  const url = process.env.UPSTASH_URL, tok = process.env.UPSTASH_TOKEN;
  const key = process.env.CCWAKE_KEY || "ccwake";
  try {
    const r = await fetch(`${url}/get/${key}`, { headers: { Authorization: `Bearer ${tok}` } });
    const j = await r.json();
    const snap = (j && j.result) ? JSON.parse(j.result) : { ts: 0, sessions: [] };
    snap.needs_token = !!process.env.CCWAKE_TOKEN;
    res.status(200).json(snap);
  } catch (e) {
    res.status(200).json({ ts: 0, sessions: [], error: String(e) });
  }
};

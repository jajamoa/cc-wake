// Publishes a whitelisted command to the relay for the host to execute.
// Only the two named actions are accepted; there is no free-form input path.
const ACTIONS = new Set(["focus", "enable_rc"]);

function authed(req) {
  const need = process.env.CCWAKE_TOKEN;
  if (!need) return true;
  const got = req.headers["x-ccwake-token"] || (req.query && req.query.token);
  return got === need;
}

module.exports = async (req, res) => {
  if (!authed(req)) return res.status(401).json({ ok: false, err: "auth" });
  const body = req.body || {};
  if (!ACTIONS.has(body.action)) return res.status(403).json({ ok: false, err: "action not allowed" });
  const url = process.env.UPSTASH_URL, tok = process.env.UPSTASH_TOKEN;
  const key = (process.env.CCWAKE_KEY || "ccwake") + ":cmd";
  try {
    await fetch(`${url}/set/${key}?EX=90`, {
      method: "POST", headers: { Authorization: `Bearer ${tok}` },
      body: JSON.stringify({ action: body.action, session_id: body.session_id }),
    });
    res.status(200).json({ ok: true });
  } catch (e) {
    res.status(200).json({ ok: false, err: String(e) });
  }
};

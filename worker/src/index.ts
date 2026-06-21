export interface Env {
  GITHUB_REPOSITORY: string;
  GITHUB_TOKEN: string;
  CF_ACCESS_AUD: string;
  CF_ACCESS_TEAM_DOMAIN: string;
  FEEDBACK_ALLOWED_ORIGIN: string;
}

type Feedback = { paper_id: string; action: "useful" | "later" | "skip"; note?: string };

const json = (body: unknown, origin: string, status = 200) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json", "access-control-allow-origin": origin, "vary": "Origin" } });

function b64(value: string): string { return btoa(unescape(encodeURIComponent(value))); }

async function verifyAccess(request: Request, env: Env): Promise<boolean> {
  const jwt = request.headers.get("Cf-Access-Jwt-Assertion");
  if (!jwt) return false;
  const issuer = `https://${env.CF_ACCESS_TEAM_DOMAIN}`;
  try {
    const jwks = await fetch(`${issuer}/cdn-cgi/access/certs`).then((response) => response.json() as Promise<JsonWebKeySet>);
    const [, encodedPayload] = jwt.split(".");
    const payload = JSON.parse(atob(encodedPayload.replace(/-/g, "+").replace(/_/g, "/")));
    const key = jwks.keys.find((item) => item.kid === JSON.parse(atob(jwt.split(".")[0].replace(/-/g, "+").replace(/_/g, "/")).kid);
    if (!key || payload.aud !== env.CF_ACCESS_AUD || payload.iss !== issuer || payload.exp * 1000 < Date.now()) return false;
    const signingInput = new TextEncoder().encode(jwt.split(".").slice(0, 2).join("."));
    const signature = Uint8Array.from(atob(jwt.split(".")[2].replace(/-/g, "+").replace(/_/g, "/")), (character) => character.charCodeAt(0));
    const cryptoKey = await crypto.subtle.importKey("jwk", key, { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" }, false, ["verify"]);
    return crypto.subtle.verify("RSASSA-PKCS1-v1_5", cryptoKey, signature, signingInput);
  } catch { return false; }
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    if (request.method === "OPTIONS") return new Response(null, { headers: { "access-control-allow-origin": env.FEEDBACK_ALLOWED_ORIGIN, "access-control-allow-methods": "POST", "vary": "Origin" } });
    if (request.method !== "POST" || request.headers.get("origin") !== env.FEEDBACK_ALLOWED_ORIGIN) return json({ error: "not found" }, env.FEEDBACK_ALLOWED_ORIGIN, 404);
    if (!(await verifyAccess(request, env))) return json({ error: "unauthorized" }, env.FEEDBACK_ALLOWED_ORIGIN, 401);
    const feedback = await request.json() as Feedback;
    if (!/^[A-Za-z0-9._:-]{1,120}$/.test(feedback.paper_id) || !["useful", "later", "skip"].includes(feedback.action)) return json({ error: "invalid feedback" }, env.FEEDBACK_ALLOWED_ORIGIN, 400);
    const id = crypto.randomUUID();
    const path = `data/feedback/${new Date().toISOString().slice(0, 10)}/${id}.json`;
    const response = await fetch(`https://api.github.com/repos/${env.GITHUB_REPOSITORY}/contents/${path}`, {
      method: "PUT",
      headers: { "authorization": `Bearer ${env.GITHUB_TOKEN}`, "accept": "application/vnd.github+json", "content-type": "application/json" },
      body: JSON.stringify({ message: `feedback: ${feedback.action} ${feedback.paper_id}`, content: b64(JSON.stringify({ ...feedback, created_at: new Date().toISOString() })) }),
    });
    return response.ok ? json({ ok: true }, env.FEEDBACK_ALLOWED_ORIGIN) : json({ error: "feedback could not be stored" }, env.FEEDBACK_ALLOWED_ORIGIN, 502);
  },
};

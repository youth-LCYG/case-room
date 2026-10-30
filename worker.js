// Case Room relay (Cloudflare Workers AI)
// Sends the game's yes/no-judge requests to an AI model on Cloudflare Workers AI,
// and makes pictures for the batch picture page (make-pictures.html).
// No outside API key is needed: the Worker uses your Cloudflare account's free daily AI allowance.
//
// Setup in the Cloudflare dashboard, on this Worker:
//   Bindings tab: Add binding > Workers AI > Variable name: AI
//   Settings > Variables and Secrets: Add > Type: Secret > Name: PASSCODE > a passcode you choose
//   (type the same passcode into the game's "Connect AI" panel)
//
// Optional plain-text variables:
//   MODEL           Workers AI model id for judging (default: @cf/openai/gpt-oss-120b)
//   IMAGE_MODEL     Workers AI model id for pictures (default: @cf/black-forest-labs/flux-2-klein-4b)
//   ALLOWED_ORIGIN  your game's address, such as https://yourname.github.io (default: any site)
//
// Open this Worker's address in a browser to check the setup.

const DEFAULT_MODEL = "@cf/openai/gpt-oss-120b";
const DEFAULT_IMAGE_MODEL = "@cf/black-forest-labs/flux-2-klein-4b";
const LIMIT_RE = /3036|neuron|allocation/i;
const BUSY_RE = /3040|capacity/i;

export default {
  async fetch(request, env) {
    const cors = {
      "Access-Control-Allow-Origin": env.ALLOWED_ORIGIN || "*",
      "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type, X-Passcode",
      "Access-Control-Max-Age": "86400",
      "Vary": "Origin"
    };

    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: cors });
    }
    if (request.method === "GET") {
      const lines = [
        "Case Room relay is running.",
        "Workers AI binding (AI): " + (env.AI ? "OK" : "MISSING - add it in the Bindings tab"),
        "PASSCODE secret: " + (env.PASSCODE ? "OK" : "MISSING - add it in Settings > Variables and Secrets"),
        "Picture making: ready (" + (env.IMAGE_MODEL || DEFAULT_IMAGE_MODEL) + ")"
      ];
      return new Response(lines.join("\n"), {
        headers: { ...cors, "Content-Type": "text/plain; charset=utf-8" }
      });
    }
    if (request.method !== "POST") return reply({ error: "method_not_allowed" }, 405, cors);
    if (!env.AI || !env.PASSCODE) return reply({ error: "not_configured" }, 500, cors);
    if (request.headers.get("X-Passcode") !== env.PASSCODE) return reply({ error: "bad_passcode" }, 401, cors);

    let body;
    try {
      body = await request.json();
    } catch (e) {
      return reply({ error: "bad_request" }, 400, cors);
    }
    const prompt = body && typeof body.prompt === "string" ? body.prompt : "";
    if (!prompt || prompt.length > 30000) return reply({ error: "bad_request" }, 400, cors);
    if (body.task === "image") return makeImage(env, body, prompt, cors);
    const effort = body.task === "grade" ? "medium" : "low";

    let text = "";
    try {
      text = await runModel(env, env.MODEL || DEFAULT_MODEL, prompt, effort);
    } catch (e) {
      return failure(e, cors);
    }
    if (!text) return reply({ error: "upstream_error", detail: "empty answer" }, 502, cors);
    return reply({ text }, 200, cors);
  }
};

// Pictures: FLUX.2 [klein] 4B takes its fields as multipart form data and returns the picture as Base64.
async function makeImage(env, body, prompt, cors) {
  if (prompt.length > 4000) return reply({ error: "bad_request" }, 400, cors);
  const form = new FormData();
  form.append("prompt", prompt);
  form.append("width", String(clampInt(body.width, 256, 1920, 1024)));
  form.append("height", String(clampInt(body.height, 256, 1920, 576)));
  if (Number.isInteger(body.seed) && body.seed >= 0) form.append("seed", String(body.seed));
  const packed = new Response(form);
  let out;
  try {
    out = await env.AI.run(env.IMAGE_MODEL || DEFAULT_IMAGE_MODEL, {
      multipart: { body: packed.body, contentType: packed.headers.get("content-type") }
    });
  } catch (e) {
    return failure(e, cors);
  }
  const image = out && typeof out.image === "string" ? out.image : "";
  if (!image) return reply({ error: "upstream_error", detail: "no picture came back" }, 502, cors);
  return reply({ image }, 200, cors);
}

function clampInt(v, min, max, fallback) {
  const n = Number.parseInt(v, 10);
  return Number.isFinite(n) ? Math.min(max, Math.max(min, n)) : fallback;
}

function failure(e, cors) {
  const msg = String((e && e.message) || e);
  if (LIMIT_RE.test(msg)) return reply({ error: "rate_limited" }, 429, cors);
  if (BUSY_RE.test(msg)) return reply({ error: "busy" }, 503, cors);
  return reply({ error: "upstream_error", detail: msg.slice(0, 200) }, 502, cors);
}

// gpt-oss on Workers AI accepts the Responses API style (input + reasoning effort).
// If that style is refused or returns nothing readable, retry with the plain messages style.
async function runModel(env, model, prompt, effort) {
  try {
    const r = await env.AI.run(model, { input: [{ role: "user", content: prompt }], reasoning: { effort } });
    const t = extractText(r);
    if (t) return t;
  } catch (e) {
    // A used-up allowance or a busy model will fail the same way on a retry.
    const msg = String((e && e.message) || e);
    if (LIMIT_RE.test(msg) || BUSY_RE.test(msg)) throw e;
  }
  const r2 = await env.AI.run(model, { messages: [{ role: "user", content: prompt }], max_tokens: 2048 });
  return extractText(r2);
}

// Pull the answer text out of the result, whichever response shape the model uses.
function extractText(r) {
  if (!r) return "";
  if (typeof r === "string") return r;
  if (typeof r.response === "string") return r.response;
  if (r.response && typeof r.response === "object") return JSON.stringify(r.response);
  if (typeof r.output_text === "string") return r.output_text;
  if (Array.isArray(r.choices) && r.choices[0]) {
    const m = r.choices[0].message;
    if (m && typeof m.content === "string") return m.content;
    if (typeof r.choices[0].text === "string") return r.choices[0].text;
  }
  if (Array.isArray(r.output)) {
    const parts = [];
    for (const item of r.output) {
      if (item && item.type === "message" && Array.isArray(item.content)) {
        for (const c of item.content) if (c && typeof c.text === "string") parts.push(c.text);
      }
    }
    if (parts.length) return parts.join("");
  }
  return "";
}

function reply(obj, status, cors) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { ...cors, "Content-Type": "application/json; charset=utf-8" }
  });
}

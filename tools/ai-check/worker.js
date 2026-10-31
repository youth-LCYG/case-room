// One-off check of the Cloudflare AI allowance, put up and taken down by .github/workflows/ai-check.yml.
// Asks the judging model for one word and reports Cloudflare's own reply or error message.
export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (!env.CHECK_KEY || url.searchParams.get("key") !== env.CHECK_KEY) return new Response("no", { status: 403 });
    try {
      const r = await env.AI.run("@cf/openai/gpt-oss-120b", {
        input: [{ role: "user", content: "Reply with the single word OK." }],
        reasoning: { effort: "low" }
      });
      return Response.json({ ok: true, reply: JSON.stringify(r).slice(0, 160) });
    } catch (e) {
      return Response.json({ ok: false, error: String((e && e.message) || e).slice(0, 500) });
    }
  }
};

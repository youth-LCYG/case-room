// Case Room rooms server (Cloudflare Worker + Durable Object)
// Lets players join a game room with a 4-letter code and take turns asking questions from their phones.
//
// How a room works
//   - The device that creates the room is its owner (the main screen, or the host's screen).
//     It runs the game and sends the whole game state here; this server passes it on to everyone else.
//   - Players join with the code and a nickname. Their questions, answers, hint requests and passes
//     are passed to the owner, who checks whose turn it is and updates the game.
//   - A big screen (projector) can join as a viewer: it only watches.
//
// Deployed by GitHub Actions (.github/workflows/rooms.yml) with the repository secrets
// CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID. Settings are in wrangler.toml.
// Durable Objects with SQLite storage are available on the Workers Free plan.

import { DurableObject } from "cloudflare:workers";

const CODE_CHARS = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"; // no I, L, O, 0, 1
const ROOM_TTL = 12 * 60 * 60 * 1000;   // a quiet room is cleared after 12 hours
const MAX_SOCKETS = 60;
const MAX_STATE = 512 * 1024;           // owner's game state message
const MAX_INTENT = 4 * 1024;            // player's message
const TOUCH_EVERY = 60 * 1000;

function allowedOrigin(origin, env) {
  if (!origin) return false;
  const list = String(env.ALLOWED_ORIGINS || "").split(",").map(s => s.trim()).filter(Boolean);
  return list.includes(origin);
}

function corsHeaders(origin, ok) {
  const h = { "Vary": "Origin", "Cache-Control": "no-store" };
  if (ok) {
    h["Access-Control-Allow-Origin"] = origin;
    h["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS";
    h["Access-Control-Allow-Headers"] = "Content-Type";
    h["Access-Control-Max-Age"] = "86400";
  }
  return h;
}

function json(data, status, origin, ok) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8", ...corsHeaders(origin, ok) }
  });
}

function makeCode() {
  const bytes = crypto.getRandomValues(new Uint8Array(4));
  return Array.from(bytes, b => CODE_CHARS[b % CODE_CHARS.length]).join("");
}

function randomHex(n) {
  return Array.from(crypto.getRandomValues(new Uint8Array(n)), b => b.toString(16).padStart(2, "0")).join("");
}

function clean(s, max) {
  return String(s || "").replace(/[\u0000-\u001f\u007f]/g, "").replace(/\s+/g, " ").trim().slice(0, max);
}

function send(ws, text) {
  try { ws.send(text); } catch (e) { /* socket already closed */ }
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const origin = request.headers.get("Origin") || "";
    const ok = allowedOrigin(origin, env);

    if (request.method === "OPTIONS") return new Response(null, { status: ok ? 204 : 403, headers: corsHeaders(origin, ok) });

    if (url.pathname === "/" && request.method === "GET") {
      return json({ ok: true, service: "case-room-rooms" }, 200, origin, ok);
    }

    // Create a room: pick a free code and get the owner's key.
    if (url.pathname === "/rooms" && request.method === "POST") {
      if (!ok) return json({ error: "origin" }, 403, origin, ok);
      for (let i = 0; i < 8; i++) {
        const code = makeCode();
        const stub = env.ROOMS.get(env.ROOMS.idFromName(code));
        const res = await stub.fetch("https://room/init", { method: "POST" });
        if (res.status === 200) {
          const { token } = await res.json();
          return json({ code, token }, 200, origin, ok);
        }
      }
      return json({ error: "busy" }, 503, origin, ok);
    }

    const m = url.pathname.match(/^\/rooms\/([A-Z0-9]{4})\/(info|ws)$/);
    if (m) {
      if (!ok) return json({ error: "origin" }, 403, origin, ok);
      const stub = env.ROOMS.get(env.ROOMS.idFromName(m[1]));
      const res = await stub.fetch(new Request(`https://room/${m[2]}${url.search}`, request));
      if (m[2] === "ws") return res;
      return new Response(res.body, { status: res.status, headers: { ...Object.fromEntries(res.headers), ...corsHeaders(origin, ok) } });
    }

    return json({ error: "not_found" }, 404, origin, ok);
  }
};

export class Room extends DurableObject {
  constructor(ctx, env) {
    super(ctx, env);
    this.lastTouch = 0;
    // Keep-alive pings are answered without waking the room.
    this.ctx.setWebSocketAutoResponse(new WebSocketRequestResponsePair("ping", "pong"));
  }

  async fetch(request) {
    const url = new URL(request.url);

    if (url.pathname === "/init") {
      const meta = await this.ctx.storage.get("meta");
      if (meta && Date.now() - meta.active < ROOM_TTL) return new Response("taken", { status: 409 });
      await this.ctx.storage.deleteAll();
      const now = Date.now();
      const token = randomHex(24);
      await this.ctx.storage.put("meta", { token, created: now, active: now });
      await this.ctx.storage.setAlarm(now + ROOM_TTL);
      return Response.json({ token });
    }

    const meta = await this.ctx.storage.get("meta");
    if (!meta) return Response.json({ error: "no_room" }, { status: 404 });

    if (url.pathname === "/info") {
      return Response.json({ ok: true, players: this.roster().length, owner: this.ctx.getWebSockets("owner").length > 0 });
    }

    if (url.pathname === "/ws") {
      if (request.headers.get("Upgrade") !== "websocket") return new Response("expected websocket", { status: 426 });
      const role = url.searchParams.get("role");
      let att;
      if (role === "owner") {
        if (url.searchParams.get("token") !== meta.token) return new Response("bad token", { status: 403 });
        att = { role };
      } else if (role === "player") {
        const pid = clean(url.searchParams.get("pid"), 40);
        const name = clean(url.searchParams.get("name"), 12);
        if (!pid || !name) return new Response("name needed", { status: 400 });
        att = { role, pid, name };
      } else if (role === "viewer") {
        att = { role };
      } else {
        return new Response("bad role", { status: 400 });
      }
      if (this.ctx.getWebSockets().length >= MAX_SOCKETS) return new Response("room full", { status: 429 });

      const pair = new WebSocketPair();
      const [client, server] = Object.values(pair);
      this.ctx.acceptWebSocket(server, [att.role]);
      server.serializeAttachment(att);
      await this.touch(true);

      const ownerOn = this.ctx.getWebSockets("owner").length > 0;
      const snapshot = await this.ctx.storage.get("snapshot");
      if (att.role === "owner") {
        // A reloaded owner gets its last game back, then the list of players who are here.
        if (snapshot) send(server, JSON.stringify({ type: "restore", state: snapshot }));
        send(server, JSON.stringify({ type: "presence", players: this.roster() }));
        this.broadcast(JSON.stringify({ type: "owner", on: true }), "owner");
      } else {
        if (snapshot) send(server, JSON.stringify({ type: "state", state: snapshot }));
        send(server, JSON.stringify({ type: "owner", on: ownerOn }));
        if (att.role === "player") this.presence();
      }
      return new Response(null, { status: 101, webSocket: client });
    }

    return new Response("not found", { status: 404 });
  }

  // Players who are connected now, one entry per player id.
  roster(except) {
    const seen = new Map();
    for (const ws of this.ctx.getWebSockets("player")) {
      if (ws === except) continue;
      const a = ws.deserializeAttachment();
      if (a && a.pid) seen.set(a.pid, { pid: a.pid, name: a.name });
    }
    return [...seen.values()];
  }

  presence(except) {
    const msg = JSON.stringify({ type: "presence", players: this.roster(except) });
    for (const ws of this.ctx.getWebSockets("owner")) send(ws, msg);
  }

  // Send to everyone except one role.
  broadcast(text, skipRole) {
    for (const ws of this.ctx.getWebSockets()) {
      const a = ws.deserializeAttachment() || {};
      if (a.role !== skipRole) send(ws, text);
    }
  }

  async touch(force) {
    const now = Date.now();
    if (!force && now - this.lastTouch < TOUCH_EVERY) return;
    this.lastTouch = now;
    const meta = await this.ctx.storage.get("meta");
    if (meta) { meta.active = now; await this.ctx.storage.put("meta", meta); }
  }

  async webSocketMessage(ws, message) {
    if (typeof message !== "string") return;
    const a = ws.deserializeAttachment() || {};
    if (a.role === "owner") {
      if (message.length > MAX_STATE) return;
      let m;
      try { m = JSON.parse(message); } catch (e) { return; }
      if (m.type === "state" && m.state && typeof m.state === "object") {
        await this.ctx.storage.put("snapshot", m.state);
        this.broadcast(JSON.stringify({ type: "state", state: m.state }), "owner");
        await this.touch(false);
      } else if (m.type === "close") {
        const out = JSON.stringify({ type: "closed" });
        for (const s of this.ctx.getWebSockets()) {
          send(s, out);
          try { s.close(1000, "room closed"); } catch (e) { /* already closed */ }
        }
        await this.ctx.storage.deleteAll();
        await this.ctx.storage.deleteAlarm();
      }
      return;
    }
    if (a.role === "player") {
      if (message.length > MAX_INTENT) return;
      let m;
      try { m = JSON.parse(message); } catch (e) { return; }
      if (m.type !== "intent" || !m.intent || typeof m.intent !== "object") return;
      const owners = this.ctx.getWebSockets("owner");
      if (!owners.length) { send(ws, JSON.stringify({ type: "error", code: "owner_offline" })); return; }
      // The player's id and name come from the connection, so nobody can act for someone else.
      const out = JSON.stringify({ type: "intent", from: { pid: a.pid, name: a.name }, intent: m.intent });
      for (const o of owners) send(o, out);
      await this.touch(false);
    }
  }

  async webSocketClose(ws, code, reason) {
    try { ws.close(code, reason); } catch (e) { /* already closed */ }
    this.left(ws);
  }

  async webSocketError(ws) {
    this.left(ws);
  }

  left(ws) {
    const a = ws.deserializeAttachment() || {};
    if (a.role === "player") this.presence(ws);
    if (a.role === "owner") {
      const still = this.ctx.getWebSockets("owner").filter(s => s !== ws).length;
      if (!still) this.broadcast(JSON.stringify({ type: "owner", on: false }), "owner");
    }
  }

  async alarm() {
    const meta = await this.ctx.storage.get("meta");
    if (!meta) return;
    if (Date.now() - meta.active >= ROOM_TTL && this.ctx.getWebSockets().length === 0) {
      await this.ctx.storage.deleteAll();
    } else {
      await this.ctx.storage.setAlarm(Date.now() + ROOM_TTL);
    }
  }
}

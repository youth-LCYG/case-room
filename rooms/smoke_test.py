"""Quick check of the live rooms server, run by the deploy workflow.
Creates a room, connects an owner and a player, and checks that messages go both ways.
Prints the result as notes on the GitHub Actions run. The test room is closed at the end."""
import asyncio, json, sys, urllib.request
import websockets

URL, ORIGIN = sys.argv[1].rstrip("/"), sys.argv[2]

def note(msg):
    print(f"::notice::{msg}", flush=True)

async def main():
    req = urllib.request.Request(f"{URL}/rooms", method="POST", headers={"Origin": ORIGIN})
    with urllib.request.urlopen(req, timeout=15) as r:
        room = json.load(r)
    code, token = room["code"], room["token"]
    ws_url = URL.replace("https://", "wss://") + f"/rooms/{code}/ws"

    async def recv(ws, want):
        while True:
            m = json.loads(await asyncio.wait_for(ws.recv(), 10))
            if m.get("type") == want:
                return m

    async with websockets.connect(f"{ws_url}?role=owner&token={token}", origin=ORIGIN) as owner:
        await recv(owner, "presence")
        async with websockets.connect(f"{ws_url}?role=player&pid=smoke&name=test", origin=ORIGIN) as player:
            joined = await recv(owner, "presence")
            assert any(p["pid"] == "smoke" for p in joined["players"]), joined
            await owner.send(json.dumps({"type": "state", "state": {"view": "home", "room": {"code": code}}}))
            got = await recv(player, "state")
            assert got["state"]["room"]["code"] == code, got
            await player.send(json.dumps({"type": "intent", "intent": {"type": "pass"}}))
            intent = await recv(owner, "intent")
            assert intent["from"]["pid"] == "smoke", intent
            await owner.send(json.dumps({"type": "close"}))
            await recv(player, "closed")
    note(f"Room test passed: created {code}, owner and player connected, messages went both ways, room closed.")

try:
    asyncio.run(main())
except Exception as e:
    print(f"::error::Room test failed: {type(e).__name__}: {e}")
    sys.exit(1)

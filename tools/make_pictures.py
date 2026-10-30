#!/usr/bin/env python3
"""Make the pictures that cases.json lists but images/ doesn't have yet.

Runs on GitHub (see .github/workflows/pictures.yml) with two repository secrets:
  RELAY_URL   the Cloudflare relay address (https://....workers.dev)
  RELAY_PASS  the relay passcode
Each picture is saved as images/<name>.jpg. Existing pictures are never touched;
to replace one, delete it and run this again (or use make-pictures.html).
"""
import base64, io, json, os, random, sys, time, urllib.error, urllib.request
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
IMAGES = ROOT / "images"
MAX_PER_RUN = int(os.environ.get("MAX_PICTURES", "24"))


def wanted(data):
    """(name, prompt) for every picture the game can show, in the same form as make-pictures.html."""
    st = data.get("pictureStyles", {})
    for p in data.get("extraPictures", []):
        yield p["name"], f"{p['scene']}\n\n{st.get(p.get('style', 'm'), '')}".strip()
    for c in data.get("cases", []):
        base = "b" if c.get("kind") == "bible" else "m"
        for slot in ("cover", "hint1", "hint2", "truth"):
            p = (c.get("pictures") or {}).get(slot)
            if p and p.get("scene"):
                # Cover and truth pictures are scene paintings; hint pictures are evidence photos.
                style = st.get(base if slot in ("cover", "truth") else base + "h", "")
                yield f"{c['id']}-{slot}", f"{p['scene']}\n\n{style}".strip()


def have(name):
    return any((IMAGES / f"{name}.{ext}").exists() for ext in ("jpg", "png"))


class Stop(Exception):
    pass


def ask_relay(url, passcode, prompt):
    body = json.dumps({"task": "image", "prompt": prompt, "width": 1024, "height": 576,
                       "seed": random.randrange(1, 2**31 - 1)}).encode()
    # A browser-like User-Agent: Cloudflare can refuse the default "Python-urllib" one.
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Content-Type": "application/json", "Accept": "application/json", "X-Passcode": passcode,
        "User-Agent": "Mozilla/5.0 (compatible; case-room-pictures/1.0; +https://github.com/youth-LCYG/case-room)"})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raw = ""
        try:
            raw = e.read().decode("utf-8", "replace")
            info = json.loads(raw)
        except Exception:
            info = {}
        code = info.get("error", "")
        if e.code == 401 or code == "bad_passcode":
            raise Stop("The relay rejected the passcode. Check the RELAY_PASS secret.")
        if e.code == 429 or code == "rate_limited":
            raise Stop("Today's free Cloudflare AI allowance is used up. The rest will be made on the next run.")
        if code == "not_configured":
            raise Stop("The relay isn't set up (Workers AI binding AI and PASSCODE secret).")
        detail = info.get("detail", "") or " ".join(raw.split())[:160]
        return {"_retry": e.code == 503, "_error": f"HTTP {e.code} {code} {detail}".strip()}
    except Exception as e:  # network trouble or timeout
        return {"_retry": True, "_error": str(e)}


def save_jpeg(b64, path):
    if b64.startswith("data:"):
        b64 = b64.split(",", 1)[1]
    img = Image.open(io.BytesIO(base64.b64decode(b64)))
    img.convert("RGB").save(path, "JPEG", quality=86, optimize=True, progressive=True)


def main():
    url = os.environ.get("RELAY_URL", "").strip()
    passcode = os.environ.get("RELAY_PASS", "").strip()
    data = json.loads((ROOT / "cases.json").read_text(encoding="utf-8"))
    todo = [(n, p) for n, p in wanted(data) if not have(n)]
    if not todo:
        print("All pictures are already there.")
        return 0
    print(f"{len(todo)} picture(s) missing: " + ", ".join(n for n, _ in todo))
    if not url.startswith(("https://", "http://")) or not passcode:
        print("::warning::RELAY_URL and RELAY_PASS secrets are not set, so no pictures were made.")
        return 0
    IMAGES.mkdir(exist_ok=True)
    made, failed, errors = [], [], []
    try:
        for name, prompt in todo[:MAX_PER_RUN]:
            for attempt in range(3):
                out = ask_relay(url, passcode, prompt)
                if isinstance(out.get("image"), str) and out["image"]:
                    save_jpeg(out["image"], IMAGES / f"{name}.jpg")
                    made.append(name)
                    print(f"made {name}.jpg")
                    break
                if "text" in out:
                    raise Stop("The relay answered with text instead of a picture. Paste the newer worker.js into Cloudflare and Deploy.")
                print(f"{name}: {out.get('_error', 'no picture came back')} (try {attempt + 1}/3)")
                errors.append(out.get("_error", "no picture came back"))
                if not out.get("_retry"):
                    break
                time.sleep(15 * (attempt + 1))
            else:
                failed.append(name)
            if name not in made and name not in failed:
                failed.append(name)
            if not made and len(failed) >= 3:
                raise Stop("The first pictures all failed, so the run stopped early. First error: " + (errors[0] if errors else "unknown"))
            time.sleep(2)
    except Stop as s:
        print(f"::warning::{s}")
        if "passcode" in str(s) or "set up" in str(s) or "newer worker" in str(s):
            print(f"Made {len(made)} picture(s) before stopping.")
            return 1 if not made else 0
    left = len(todo) - len(made)
    print(f"Made {len(made)} picture(s). {left} still missing.")
    if failed:
        print("::warning::Couldn't make: " + ", ".join(failed) + (f". First error: {errors[0]}" if errors else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())

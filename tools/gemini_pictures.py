#!/usr/bin/env python3
"""Make the missing pictures once with Google's Gemini API (Nano Banana 2).

Runs on GitHub (.github/workflows/gemini-pictures.yml), started by hand, with the repository
secret GEMINI_API_KEY (a Google AI Studio API key on a prepaid billing account).

Spending stays small and bounded:
  - only pictures that cases.json lists and images/ doesn't have yet (or the names given in ONLY);
  - at most MAX_PICTURES pictures per run (default 40);
  - it stops before the estimated cost would pass BUDGET_USD (default 4.00);
  - with a prepaid balance, Google itself stops every request when the balance reaches $0.
A refused or failed picture is reported and skipped, never retried in a loop.
"""
import base64, io, json, os, re, sys, time, urllib.error, urllib.request
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
IMAGES = ROOT / "images"
sys.path.insert(0, str(ROOT / "tools"))
from make_pictures import wanted, have  # same picture names and prompts as the rest of the project

API = os.environ.get("GEMINI_API_BASE", "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
KEY = os.environ.get("GEMINI_API_KEY", "").strip()
MAX_PICTURES = int(os.environ.get("MAX_PICTURES", "40") or 40)
BUDGET = float(os.environ.get("BUDGET_USD", "4.00") or 4.0)
ONLY = [s.strip() for s in os.environ.get("ONLY", "").replace("\n", ",").split(",") if s.strip()]
CHECK_ONLY = os.environ.get("CHECK_ONLY", "").strip().lower() == "true"   # check the key and stop, at no cost
# Answers that mean every request will fail the same way (no paid access, no balance): stop at once.
FATAL = re.compile(r"limit: ?0\b|billing|prepa|credit|payment", re.I)
# Cheapest suitable models first. Prices from ai.google.dev/pricing (paid tier, one 1K picture).
MODELS = [
    ("gemini-3.1-flash-image-preview", 0.067),
    ("gemini-3.1-flash-image", 0.067),
    ("gemini-2.5-flash-image", 0.039),
]
TEXT_OUT = 3.00 / 1_000_000   # thinking and text output, per token (Gemini 3.1 Flash Image)
TEXT_IN = 0.50 / 1_000_000    # prompt, per token
W, H = 1024, 576              # the shape the game shows (16:9)
UA = "Mozilla/5.0 (compatible; case-room-pictures/2.0; +https://github.com/youth-LCYG/case-room)"


class Stop(Exception):
    pass


def call(method, path, body=None, timeout=240):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{API}/{path}", data=data, method=method, headers={
        "Content-Type": "application/json", "x-goog-api-key": KEY, "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        try:
            info = json.loads(e.read().decode("utf-8", "replace") or "{}")
        except Exception:
            info = {}
        return e.code, info
    except Exception as e:  # network trouble or timeout
        return 0, {"error": {"message": str(e)}}


def message(info):
    err = (info or {}).get("error") or {}
    return f"{err.get('status', '')} {err.get('message', '')}".strip()[:300]


def pick_model():
    status, info = call("GET", "models?pageSize=1000", timeout=60)
    if status in (401, 403):
        raise Stop(f"Google refused the API key ({status}): {message(info)}. Check the GEMINI_API_KEY secret.")
    if status != 200:
        raise Stop(f"Couldn't list the models ({status}): {message(info)}")
    names = {m.get("name", "").split("/")[-1] for m in info.get("models", [])}
    for model, price in MODELS:
        if model in names:
            return model, price
    raise Stop("None of the expected picture models is available to this key: " + ", ".join(m for m, _ in MODELS))


def picture_from(info):
    """The final picture in the answer (thought pictures, which Google doesn't charge for, are skipped)."""
    parts = []
    for cand in info.get("candidates", []) or []:
        parts += ((cand.get("content") or {}).get("parts") or [])
    final = [p for p in parts if not p.get("thought") and (p.get("inlineData") or p.get("inline_data"))]
    if not final:
        return None
    blob = final[-1].get("inlineData") or final[-1].get("inline_data")
    return base64.b64decode(blob.get("data", ""))


def why_none(info):
    fb = info.get("promptFeedback") or {}
    if fb.get("blockReason"):
        return f"refused ({fb['blockReason']})"
    reasons = {c.get("finishReason") for c in info.get("candidates", []) or [] if c.get("finishReason")}
    texts = [p.get("text", "") for c in info.get("candidates", []) or [] for p in ((c.get("content") or {}).get("parts") or []) if p.get("text") and not p.get("thought")]
    return ("finished with " + ", ".join(sorted(reasons)) if reasons else "no picture") + (f": {texts[0][:160]}" if texts else "")


def save(raw, path):
    img = Image.open(io.BytesIO(raw)).convert("RGB")
    w, h = img.size
    if w / h > W / H:          # too wide: trim the sides
        nw = round(h * W / H)
        img = img.crop(((w - nw) // 2, 0, (w - nw) // 2 + nw, h))
    elif w / h < W / H:        # too tall: trim top and bottom
        nh = round(w * H / W)
        img = img.crop((0, (h - nh) // 2, w, (h - nh) // 2 + nh))
    img.resize((W, H), Image.LANCZOS).save(path, "JPEG", quality=86, optimize=True, progressive=True)


def note(kind, text):
    print(f"::{kind}::{text}" if os.environ.get("GITHUB_ACTIONS") else f"[{kind}] {text}")


def main():
    if not KEY:
        note("error", "The GEMINI_API_KEY secret is missing, so nothing was made.")
        return 1
    data = json.loads((ROOT / "cases.json").read_text(encoding="utf-8"))
    every = list(wanted(data))
    if ONLY:
        known = {n for n, _ in every}
        unknown = [n for n in ONLY if n not in known]
        if unknown:
            note("error", "Not picture names from cases.json: " + ", ".join(unknown))
            return 1
        todo = [(n, p) for n, p in every if n in ONLY]
    else:
        todo = [(n, p) for n, p in every if not have(n)]
    if not todo:
        print("All pictures are already there.")
        return 0
    todo = todo[:MAX_PICTURES]
    try:
        model, price = pick_model()
    except Stop as s:
        note("error", str(s))
        return 1
    print(f"Model: {model} (${price:.3f} per picture). {len(todo)} picture(s) to make. Budget ${BUDGET:.2f}.")
    if CHECK_ONLY:
        note("notice", f"The key works and {model} is available. {len(todo)} picture(s) would be made, about ${len(todo) * price:.2f}. Nothing was made.")
        return 0
    IMAGES.mkdir(exist_ok=True)
    spent, made, failed, errors_in_row = 0.0, [], [], 0
    for i, (name, prompt) in enumerate(todo, 1):
        if spent + price + 0.01 > BUDGET:
            note("warning", f"Stopped before {name}: the next picture could pass the ${BUDGET:.2f} budget (about ${spent:.2f} so far).")
            break
        config = {"responseModalities": ["TEXT", "IMAGE"], "imageConfig": {"aspectRatio": "16:9"}}
        if model.startswith("gemini-3"):
            config["imageConfig"]["imageSize"] = "1K"
        body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}], "generationConfig": config}
        info, status = {}, 0
        for attempt in range(3):   # only "busy" answers are tried again; Google doesn't charge for those
            status, info = call("POST", f"models/{model}:generateContent", body)
            if status in (429, 500, 503, 0):
                time.sleep(20 * (attempt + 1))
                continue
            break
        if status == 402:
            note("warning", "Google stopped the requests: the prepaid balance is used up.")
            break
        if status != 200 and FATAL.search(message(info)):
            note("error", f"Google won't make pictures with this key yet ({status}): {message(info)}")
            break
        if status in (401, 403):
            note("error", f"Google refused the API key ({status}): {message(info)}")
            break
        if status != 200:
            failed.append(name)
            errors_in_row += 1
            note("warning", f"{name}: Google answered {status} {message(info)}")
            if errors_in_row >= 3:
                note("error", "Three pictures in a row failed the same way, so the run stopped.")
                break
            continue
        errors_in_row = 0
        usage = info.get("usageMetadata") or {}
        cost = price + TEXT_OUT * (usage.get("thoughtsTokenCount") or 0) + TEXT_IN * (usage.get("promptTokenCount") or 0)
        raw = picture_from(info)
        if not raw:
            spent += TEXT_OUT * (usage.get("thoughtsTokenCount") or 0) + TEXT_IN * (usage.get("promptTokenCount") or 0)
            failed.append(name)
            note("warning", f"{name}: {why_none(info)}")
            continue
        try:
            save(raw, IMAGES / f"{name}.jpg")
        except Exception as e:
            failed.append(name)
            note("warning", f"{name}: the picture couldn't be read ({e})")
            continue
        spent += cost
        made.append(name)
        print(f"{i:02d}/{len(todo)} made {name}.jpg (about ${spent:.2f} so far)")
        time.sleep(3)
    note("notice", f"Made {len(made)} picture(s) with {model}, about ${spent:.2f} in all.")
    if failed:
        note("warning", "Not made: " + ", ".join(failed))
    return 0


if __name__ == "__main__":
    sys.exit(main())

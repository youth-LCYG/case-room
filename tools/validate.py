#!/usr/bin/env python3
"""Check cases.json before uploading it.

Usage:  python3 tools/validate.py [path/to/cases.json]
Prints problems and exits with status 1 if anything must be fixed.
"""
import json, re, sys

path = sys.argv[1] if len(sys.argv) > 1 else "cases.json"
errors, warnings = [], []

def err(msg): errors.append(msg)
def warn(msg): warnings.append(msg)

def bilingual(obj, where, max_len=None):
    if not isinstance(obj, dict):
        err(f"{where}: needs both 'en' and 'ko'"); return
    for lang in ("en", "ko"):
        v = obj.get(lang)
        if not isinstance(v, str) or not v.strip():
            err(f"{where}.{lang}: missing")
        elif max_len and len(v) > max_len:
            warn(f"{where}.{lang}: {len(v)} characters (over {max_len})")

# Words that must not appear in what players see in a mystery (no death, no suicide, no violence).
BANNED_EN = re.compile(r"\b(dead|died|dies|die|dying|death|kill\w*|murder\w*|suicid\w*|corpse|blood\w*|bleed\w*|gun|knife|stab\w*)\b", re.I)
BANNED_KO = re.compile(r"(죽었|죽은|죽음|죽이|죽기|죽고|죽어|살해|자살|시체|숨졌|피를 흘|총을|칼로)")

def visible_texts(c):
    yield "title", c.get("title", {})
    yield "setup", c.get("setup", {})
    yield "truth", c.get("truth", {})
    for i, k in enumerate(c.get("keys", [])):
        yield f"keys[{i}].label", k.get("label", {})
        yield f"keys[{i}].text", k.get("text", {})
    for i, h in enumerate(c.get("hints", [])):
        yield f"hints[{i}]", h

SLOTS = ("cover", "hint1", "hint2", "truth")

def check_story(c, w):
    """The parts every telling of a case needs: key points, two hints, judging notes."""
    keys = c.get("keys", [])
    if not 2 <= len(keys) <= 5: err(f"{w} keys: need 2 to 5 key points")
    kids = set()
    for i, k in enumerate(keys):
        if not k.get("id"): err(f"{w} keys[{i}].id: missing")
        if k.get("id") in kids: err(f"{w} keys[{i}].id repeats")
        kids.add(k.get("id"))
        bilingual(k.get("label"), f"{w} keys[{i}].label")
        bilingual(k.get("text"), f"{w} keys[{i}].text")
    hints = c.get("hints", [])
    if len(hints) != 2: err(f"{w} hints: need exactly 2")
    for i, h in enumerate(hints): bilingual(h, f"{w} hints[{i}]")
    if not isinstance(c.get("facts"), str) or len(c.get("facts", "")) < 80:
        err(f"{w} facts: missing or too short")
    # Korean judging notes for the host screen. Optional: the English is shown when they are missing.
    for en_key, ko_key in (("facts", "factsKo"), ("notStated", "notStatedKo")):
        if en_key not in c:
            continue
        if ko_key not in c:
            warn(f"{w} {ko_key}: missing, so the host screen shows the English {en_key}")
            continue
        ko, en = c[ko_key], c.get(en_key)
        if not isinstance(ko, str) or not ko.strip():
            err(f"{w} {ko_key}: empty")
        elif isinstance(en, str) and ko.count("\n") != en.count("\n"):
            warn(f"{w} {ko_key}: {ko.count(chr(10)) + 1} lines but {en_key} has {en.count(chr(10)) + 1}; check that they match")

def check_adult(c, w):
    """College version of a mystery: a second telling, shown only with the college link (?group=college)."""
    a = c.get("adult")
    w = f"{w} adult"
    if c.get("kind") != "mystery": err(f"{w}: only mysteries can have a college version")
    if not isinstance(a, dict):
        err(f"{w}: must be an object"); return
    if a.get("level") not in (1, 2, 3): err(f"{w} level: must be 1, 2 or 3")
    bilingual(a.get("title"), f"{w} title", 60)
    bilingual(a.get("setup"), f"{w} setup", 700)
    bilingual(a.get("truth"), f"{w} truth")
    check_story(a, w)
    pics = a.get("pictures", {})
    if not isinstance(pics, dict):
        err(f"{w} pictures: must be an object"); return
    for slot in SLOTS:
        p = pics.get(slot)
        if p is None or (isinstance(p, str) and p in SLOTS):
            continue  # the youth picture is used
        if isinstance(p, str):
            err(f"{w} pictures.{slot}: \"{p}\" is not a picture slot (use cover, hint1, hint2 or truth)")
        elif not isinstance(p, dict) or not p.get("scene") or not p.get("check"):
            err(f"{w} pictures.{slot}: a new picture needs scene and check")

try:
    data = json.load(open(path, encoding="utf-8"))
except Exception as e:
    print(f"Can't read {path}: {e}"); sys.exit(1)

styles = data.get("pictureStyles", {})
for s in ("m", "b", "mh", "bh"):
    if not isinstance(styles.get(s), str) or not styles[s].strip():
        err(f"pictureStyles.{s}: missing")
for i, p in enumerate(data.get("extraPictures", [])):
    for f in ("name", "scene", "check", "style"):
        if not p.get(f): err(f"extraPictures[{i}].{f}: missing")

cases = data.get("cases")
if not isinstance(cases, list) or not cases:
    err("cases: missing or empty"); cases = []
cap = data.get("maxCases", 30)
if len(cases) > cap:
    err(f"{len(cases)} cases, but the limit (maxCases) is {cap}")

seen = set()
for n, c in enumerate(cases):
    cid = c.get("id", f"#{n}")
    w = f"[{cid}]"
    if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", str(c.get("id", ""))):
        err(f"{w} id: use lowercase letters, numbers and hyphens")
    if cid in seen: err(f"{w} id is used twice")
    seen.add(cid)
    kind = c.get("kind")
    if kind not in ("mystery", "bible"): err(f"{w} kind: must be 'mystery' or 'bible'")
    if c.get("level") not in (1, 2, 3): err(f"{w} level: must be 1, 2 or 3")
    bilingual(c.get("title"), f"{w} title", 60)
    bilingual(c.get("setup"), f"{w} setup", 700)
    bilingual(c.get("truth"), f"{w} truth")
    check_story(c, w)
    if "adult" in c:
        check_adult(c, w)
    pics = c.get("pictures", {})
    for slot in SLOTS:
        p = pics.get(slot, {})
        if not p.get("scene"): err(f"{w} pictures.{slot}.scene: missing")
        if not p.get("check"): err(f"{w} pictures.{slot}.check: missing")
    if kind == "bible":
        bilingual(c.get("ref"), f"{w} ref")
        bilingual(c.get("abbr"), f"{w} abbr")
        sil = c.get("silent", [])
        if not sil: err(f"{w} silent: add at least one thing the text doesn't say")
        for i, s in enumerate(sil): bilingual(s, f"{w} silent[{i}]")
        if not isinstance(c.get("notStated"), str) or not c["notStated"].strip():
            err(f"{w} notStated: missing")
    # Death, suicide and violence stay out of what players see (the college versions are exempt).
    for where, obj in visible_texts(c):
        for lang, rx in (("en", BANNED_EN), ("ko", BANNED_KO)):
            m = rx.search((obj or {}).get(lang, "") if isinstance(obj, dict) else "")
            if m:
                msg = f"{w} {where}.{lang}: contains \"{m.group(0)}\""
                (err if kind == "mystery" else warn)(msg)

print(f"{len(cases)} cases checked ({sum(c.get('kind')=='mystery' for c in cases)} mysteries, {sum(c.get('kind')=='bible' for c in cases)} Bible, "
      f"{sum('adult' in c for c in cases)} college versions), limit {cap}.")
for m in warnings: print("note:", m)
for m in errors: print("FIX:", m)
print("OK" if not errors else f"{len(errors)} problem(s) to fix.")
sys.exit(1 if errors else 0)

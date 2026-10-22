"""Link each note in a deck to the best-matching heading of a Bear note, then push the links to the app.

Runs on the Mac where Bear lives (reads Bear's SQLite read-only) and talks to the app over HTTP, so it
works for both the local and the deployed instance:

  uv run python tools/bear_link.py --deck Math4ML --bear-note BE5759A7-C98C-40E8-A3FC-A2E20506195A \\
      --map tools/maps/math4ml.json --url https://fsrs-cards-8378.fly.dev --password ... [--dry-run]

Matching = TF-IDF cosine between the card's text and each heading's section text, plus a bonus for headings
the optional --map file lists for the card's deck section (the deck's "Section" field or subdeck name).
"""
import argparse
import json
import math
import re
import shutil
import sqlite3
import sys
import tempfile
import urllib.parse
import urllib.request
from collections import Counter
from http.cookiejar import CookieJar
from pathlib import Path

BEAR_DB = Path.home() / "Library/Group Containers/9K33E3U3T4.net.shinyfrog.bear/Application Data/database.sqlite"
SKIP_FIELDS = {"level", "levelclass", "kind", "image", "section", "source"}
STOP = set("""a an the of and or to in on for is are be by with as at from that this it its if then than so
what which how why when where who does do can into not no yes vs via e g i ie eg x y p q we you your our their
there these those such each per one two three only also just more most less very same over under about between
give name explain describe write state define""".split())


def tokens(text: str) -> list[str]:
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\\(mathbb|mathrm|text|textbf|left|right|cdot|frac|sqrt|sum|log)\b", r" \1 ", text)
    out = []
    for w in re.findall(r"[a-zA-Z]{2,}", text.lower()):
        if w in STOP:
            continue
        for suf in ("ization", "ations", "ation", "ings", "ing", "ies", "es", "s"):
            if len(w) > len(suf) + 3 and w.endswith(suf):
                w = w[: -len(suf)]
                break
        out.append(w)
    return out


def bear_sections(note_id: str):
    with tempfile.TemporaryDirectory() as tmp:  # copy so we never touch Bear's live DB
        db = Path(tmp) / "bear.sqlite"
        shutil.copy(BEAR_DB, db)
        row = sqlite3.connect(db).execute(
            "SELECT ZTITLE, ZTEXT FROM ZSFNOTE WHERE ZUNIQUEIDENTIFIER = ?", (note_id,)).fetchone()
    if not row:
        sys.exit(f"Bear note {note_id} not found")
    title, text = row
    sections, cur = [], None
    for line in text.splitlines():
        m = re.match(r"^(#{1,6})\s+(.*\S)\s*$", line)
        if m:
            cur = {"level": len(m.group(1)), "header": m.group(2).strip(), "text": m.group(2) + "\n"}
            sections.append(cur)
        elif cur:
            cur["text"] += line + "\n"
    return title, [s for s in sections if s["level"] > 1 or len(sections) == 1]


def bear_url(note_id: str, header: str | None) -> str:
    q = {"id": note_id}
    if header:
        q["header"] = header
    return "bear://x-callback-url/open-note?" + urllib.parse.urlencode(q, quote_via=urllib.parse.quote)


class Api:
    def __init__(self, base: str, password: str | None):
        self.base = base.rstrip("/")
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))
        if password:
            self.call("/api/login", {"password": password})

    def call(self, path, body=None):
        req = urllib.request.Request(self.base + path, data=None if body is None else json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        return json.load(self.opener.open(req))


def apply_manual(a):
    spec = json.loads(Path(a.manual).read_text())
    note_id = spec.get("bear_note") or a.bear_note
    title, sections = bear_sections(note_id)
    known = {s["header"] for s in sections}
    out = {}
    for nid, v in spec["notes"].items():
        h = v.get("header")
        if h and h not in known:
            sys.exit(f"header {h!r} (note {nid}) not found in Bear note '{title}'")
        out[int(nid)] = {"url": bear_url(note_id, h), "label": f"{title} › {h}"} if h else {"url": None, "label": None}
    linked = sum(1 for v in out.values() if v["url"])
    print(f"{linked} notes linked, {len(out) - linked} without a reference")
    if not a.dry_run:
        print(Api(a.url, a.password).call("/api/notes/sources", {"sources": out}))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--deck")
    ap.add_argument("--bear-note", help="Bear note unique id")
    ap.add_argument("--map", help="JSON: {deck section prefix: [preferred headers]}")
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    ap.add_argument("--password")
    ap.add_argument("--bonus", type=float, default=0.25, help="score bonus for headers listed in --map")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--report", help="write a CSV of note -> header assignments")
    ap.add_argument("--manual", help="JSON {bear_note, notes: {note_id: {header|null}}} — hand-curated links; skips matching")
    a = ap.parse_args()
    if a.manual:
        return apply_manual(a)

    title, sections = bear_sections(a.bear_note)
    prior = json.loads(Path(a.map).read_text()) if a.map else {}
    known = {s["header"] for s in sections}
    for k, hs in prior.items():
        for h in hs:
            if h not in known:
                sys.exit(f"--map header not in Bear note: {h!r} (have: {sorted(known)})")

    api = Api(a.url, a.password)
    notes = api.call("/api/notes?" + urllib.parse.urlencode({"deck": a.deck}))
    docs = [Counter(tokens(s["text"])) for s in sections]
    df = Counter(t for d in docs for t in d)
    N = len(docs)
    idf = {t: math.log((N + 1) / (n + 1)) + 1 for t, n in df.items()}

    def vec(c):
        v = {t: (1 + math.log(n)) * idf.get(t, 0) for t, n in c.items() if t in idf}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1
        return {t: x / norm for t, x in v.items()}

    svecs = [vec(d) for d in docs]
    out, rows = {}, []
    for n in notes:
        f = {k: v for k, v in n["fields"].items()}
        section = next((v for k, v in f.items() if k.lower() == "section"), "") or n["deck"].split("::")[-1]
        text = " ".join(v for k, v in f.items() if k.lower() not in SKIP_FIELDS)
        nv = vec(Counter(tokens(text)))
        preferred = next((hs for k, hs in prior.items() if section.startswith(k)), [])
        scored = []
        for s, sv in zip(sections, svecs):
            sim = sum(x * sv.get(t, 0) for t, x in nv.items())
            scored.append((sim + (a.bonus if s["header"] in preferred else 0), sim, s["header"]))
        scored.sort(reverse=True)
        best = scored[0]
        out[n["id"]] = {"url": bear_url(a.bear_note, best[2]), "label": f"{title} › {best[2]}"}
        front = re.sub(r"<[^>]+>", "", next(iter(f.values()), ""))[:70]
        rows.append((section, best[2], round(best[1], 3), front))

    by = Counter(r[1] for r in rows)
    print(f"{len(rows)} notes → {len(by)} headings of Bear note '{title}':")
    for h, c in by.most_common():
        print(f"  {c:4d}  {h}")
    if a.report:
        import csv
        with open(a.report, "w", newline="") as fh:
            csv.writer(fh).writerows([("deck_section", "bear_header", "similarity", "front"), *rows])
        print("report:", a.report)
    if not a.dry_run:
        print(api.call("/api/notes/sources", {"sources": out}))


if __name__ == "__main__":
    main()

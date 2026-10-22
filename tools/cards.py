"""Read and write cards in the app's database (the live Fly app by default). The database is the source of truth;
.apkg files are only for bringing in outside decks once (tools/import_apkg.py).

  uv run python tools/cards.py types                                   # note types and their fields
  uv run python tools/cards.py list --deck "Math4ML" --q softmax       # id · deck · type · front
  uv run python tools/cards.py show 1792626439797                      # one note as JSON
  uv run python tools/cards.py add note.json                           # {"notetype", "deck", "fields", "tags"} or a list
  uv run python tools/cards.py add --type "Math4ML · Basic" --deck "Math4ML::…" -f Front="…" -f Back=@back.html
  uv run python tools/cards.py edit 1792626439797 -f Back=@back.html [--tags "…"] [--deck "…"] [--reset]
  uv run python tools/cards.py edit changes.json                       # {"id", "fields", ...} or a list
  uv run python tools/cards.py rm 1792626439797
  uv run python tools/cards.py suspend 1792626439797 [more ids] --reason "…"   # or --undo
  uv run python tools/cards.py export                                  # decks/<deck>.json, for history in git

--url defaults to the live app (.fly-app-name) and --password to .app-password; use --url http://127.0.0.1:8000
for the local app. Field values starting with @ are read from that file.
"""
import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _read(name: str) -> str:
    p = ROOT / name
    return p.read_text().strip() if p.exists() else ""


class Client:
    def __init__(self, url: str, password: str):
        self.base = url.rstrip("/")
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))
        self.admin = os.environ.get("ADMIN_TOKEN") or _read(".admin-token")
        if password:
            self("POST", "/api/login", {"password": password})

    def __call__(self, method: str, path: str, body=None):
        req = urllib.request.Request(self.base + path, method=method,
                                     data=None if body is None else json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json", "X-Admin-Token": self.admin})
        try:
            return json.load(self.opener.open(req))
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")
            try:
                detail = json.loads(detail)["detail"]
            except Exception:
                pass
            sys.exit(f"{method} {path} → {e.code}: {detail}")


def strip(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html or "")).strip()


def field_args(pairs: list[str]) -> dict:
    out = {}
    for p in pairs or []:
        k, sep, v = p.partition("=")
        if not sep:
            sys.exit(f"--field expects NAME=VALUE, got {p!r}")
        out[k] = Path(v[1:]).read_text() if v.startswith("@") else v
    return out


def load_json(path: str):
    data = json.loads(Path(path).read_text())
    return data if isinstance(data, list) else [data]


def summary(n: dict) -> str:
    front = strip(next(iter(n["fields"].values()), ""))
    states = ",".join("suspended" if c["suspended"] else c["state"] for c in n["cards"])
    return f"{n['id']}  {n['deck'].split('::')[-1][:28]:28}  {n['notetype'][:18]:18}  {states:10}  {front[:90]}"


def slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_").lower()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default=f"https://{_read('.fly-app-name') or 'fsrs-cards-8378'}.fly.dev")
    ap.add_argument("--password", default=os.environ.get("APP_PASSWORD") or _read(".app-password"))
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("types")
    p = sub.add_parser("list"); p.add_argument("--deck"); p.add_argument("--q", default="")
    p = sub.add_parser("show"); p.add_argument("id", type=int)
    p = sub.add_parser("add"); p.add_argument("file", nargs="?"); p.add_argument("--type"); p.add_argument("--deck")
    p.add_argument("-f", "--field", action="append"); p.add_argument("--tags", default="")
    p = sub.add_parser("edit"); p.add_argument("target"); p.add_argument("-f", "--field", action="append")
    p.add_argument("--tags"); p.add_argument("--deck"); p.add_argument("--reset", action="store_true",
                                                                      help="reset the cards' memory state (question changed)")
    p = sub.add_parser("rm"); p.add_argument("id", type=int)
    p = sub.add_parser("suspend", help="suspend (or --undo) every card of these notes")
    p.add_argument("ids", type=int, nargs="+"); p.add_argument("--reason"); p.add_argument("--undo", action="store_true")
    p = sub.add_parser("export"); p.add_argument("--out", default=str(ROOT / "decks"))
    a = ap.parse_args()
    api = Client(a.url, a.password)

    if a.cmd == "types":
        for t in api("GET", "/api/notetypes"):
            print(f"{t['id']}  {t['name']}{'  (cloze)' if t['cloze'] else ''}\n    fields: {', '.join(t['fields'])}")
    elif a.cmd == "list":
        qs = "&".join(f"{k}={urllib.request.quote(v)}" for k, v in (("deck", a.deck), ("q", a.q)) if v)
        notes = api("GET", "/api/notes" + (f"?{qs}" if qs else ""))
        for n in notes:
            print(summary(n))
        print(f"{len(notes)} notes", file=sys.stderr)
    elif a.cmd == "show":
        print(json.dumps(api("GET", f"/api/notes/{a.id}"), ensure_ascii=False, indent=2))
    elif a.cmd == "add":
        notes = load_json(a.file) if a.file else [{"notetype": a.type, "deck": a.deck, "fields": field_args(a.field),
                                                   "tags": a.tags}]
        for n in notes:
            print("added", summary(api("POST", "/api/notes", n)))
    elif a.cmd == "edit":
        if a.target.isdigit():
            changes = [{"id": int(a.target), "fields": field_args(a.field), "tags": a.tags, "deck": a.deck,
                        "reset_cards": a.reset}]
        else:
            changes = load_json(a.target)
        for ch in changes:
            nid = ch.pop("id")
            print("edited", summary(api("PUT", f"/api/notes/{nid}", {k: v for k, v in ch.items() if v is not None})))
    elif a.cmd == "rm":
        n = api("GET", f"/api/notes/{a.id}")
        print(summary(n))
        if input(f"Delete this note, {len(n['cards'])} card(s) and their review history? [y/N] ").lower() != "y":
            return
        print(api("DELETE", f"/api/notes/{a.id}"))
    elif a.cmd == "suspend":
        for nid in a.ids:
            n = api("GET", f"/api/notes/{nid}")
            for c in n["cards"]:
                api("POST", f"/api/cards/{c['id']}/suspend", {"suspended": not a.undo, "reason": a.reason})
            print("unsuspended" if a.undo else "suspended", summary(api("GET", f"/api/notes/{nid}")))
    elif a.cmd == "export":
        # content only (no scheduling state), so git diffs show what you actually changed
        by_deck: dict[str, list] = {}
        for n in api("GET", "/api/notes"):
            top = n["deck"].split("::")[0]
            by_deck.setdefault(top, []).append({
                "id": n["id"], "deck": n["deck"], "notetype": n["notetype"], "tags": n["tags"], "fields": n["fields"],
                "source_url": n["source_url"], "source_label": n["source_label"],
                "suspended": [c["suspend_reason"] or True for c in n["cards"] if c["suspended"]] or None})
        out = Path(a.out)
        out.mkdir(parents=True, exist_ok=True)
        for top, notes in sorted(by_deck.items()):
            notes.sort(key=lambda x: (x["deck"], x["id"]))
            (out / f"{slug(top)}.json").write_text(json.dumps(notes, ensure_ascii=False, indent=1) + "\n")
            print(f"{len(notes):4} notes → {out / (slug(top) + '.json')}")


if __name__ == "__main__":
    main()

"""Pull the suspended-card rewrite queue from the app to local files.

  uv run python tools/export_suspended.py --url https://fsrs-cards-8378.fly.dev --password ...

Writes review/suspended.json (full data, incl. original HTML fields) and review/suspended.md (readable list,
grouped by deck, with reason, review stats and the Bear source link).
"""
import argparse
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from bear_link import Api


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    ap.add_argument("--password")
    ap.add_argument("--deck")
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent.parent / "review"))
    a = ap.parse_args()

    path = "/api/suspended" + (f"?deck={a.deck}" if a.deck else "")
    cards = Api(a.url, a.password).call(path)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "suspended.json").write_text(json.dumps(cards, ensure_ascii=False, indent=1))

    by_deck = defaultdict(list)
    for c in cards:
        by_deck[c["deck"]].append(c)
    lines = [f"# Suspended cards — rewrite queue ({len(cards)})", "",
             f"_Exported {datetime.now():%Y-%m-%d %H:%M} from {a.url}_", ""]
    for deck, cs in sorted(by_deck.items()):
        lines += [f"## {deck}", ""]
        for c in cs:
            f = c["fields"]
            q = f.get("Front") or f.get("Text") or f.get("Problem") or next(iter(f.values()), "")
            ans = f.get("Back") or f.get("Answer") or f.get("Extra") or ""
            when = datetime.fromtimestamp(c["suspended_at"]).strftime("%Y-%m-%d") if c["suspended_at"] else "before tracking"
            stats = f"{c['reviews']} reviews, {c['again_count']} Again" + (f", D {c['difficulty']:.1f}" if c["difficulty"] else "")
            lines += [f"- **{q.strip()}**", f"  - Answer: {ans.strip()[:400]}",
                      f"  - Reason: {c['reason'] or '—'} · suspended {when} · {stats}"]
            if c["source_url"]:
                lines.append(f"  - Source: [{c['source_label']}]({c['source_url']})")
            lines.append(f"  - ids: card {c['card_id']}, note {c['note_id']}")
        lines.append("")
    (out / "suspended.md").write_text("\n".join(lines))
    print(f"{len(cards)} suspended cards → {out}/suspended.md, suspended.json")


if __name__ == "__main__":
    main()

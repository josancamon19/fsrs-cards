"""Import Anki .apkg / .colpkg files (legacy anki2/anki21 and modern zstd anki21b)."""
import html
import json
import os
import re
import sqlite3
import tempfile
import zipfile
from collections import defaultdict
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import zstandard

from . import db, sched

ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"


def _unzstd(data: bytes) -> bytes:
    if data[:4] != ZSTD_MAGIC:
        return data
    return zstandard.ZstdDecompressor().decompressobj().decompress(data)


# --- minimal protobuf reader (enough for Anki's notetype/template/media configs)

def _varint(buf: bytes, i: int) -> tuple[int, int]:
    shift = result = 0
    while True:
        b = buf[i]
        i += 1
        result |= (b & 0x7F) << shift
        if not b & 0x80:
            return result, i
        shift += 7


def pb_decode(buf: bytes) -> dict[int, list]:
    out: dict[int, list] = defaultdict(list)
    i = 0
    while i < len(buf):
        key, i = _varint(buf, i)
        field, wt = key >> 3, key & 7
        if wt == 0:
            v, i = _varint(buf, i)
        elif wt == 1:
            v, i = buf[i:i + 8], i + 8
        elif wt == 2:
            ln, i = _varint(buf, i)
            v, i = buf[i:i + ln], i + ln
        elif wt == 5:
            v, i = buf[i:i + 4], i + 4
        else:
            raise ValueError(f"unsupported wire type {wt}")
        out[field].append(v)
    return out


def _pb_str(d, f, default=""):
    return d[f][0].decode("utf-8", "replace") if d.get(f) else default


def _pb_int(d, f, default=0):
    return d[f][0] if d.get(f) else default


# --- collection readers

def _read_models_legacy(src: sqlite3.Connection):
    models_json, decks_json = src.execute("SELECT models, decks FROM col").fetchone()
    models = {}
    for mid, m in json.loads(models_json).items():
        flds = sorted(m["flds"], key=lambda f: f["ord"])
        tmpls = sorted(m["tmpls"], key=lambda t: t["ord"])
        models[int(mid)] = dict(
            name=m["name"], kind=int(m.get("type", 0)), fields=[f["name"] for f in flds],
            templates=[{"name": t["name"], "qfmt": t["qfmt"], "afmt": t["afmt"]} for t in tmpls],
            css=m.get("css", ""))
    decks = {int(did): d["name"] for did, d in json.loads(decks_json).items()}
    return models, decks


def _read_models_v18(src: sqlite3.Connection):
    models = {}
    for ntid, name, config in src.execute("SELECT id, name, config FROM notetypes"):
        cfg = pb_decode(config)
        models[ntid] = dict(name=name, kind=_pb_int(cfg, 1), fields=[], templates=[], css=_pb_str(cfg, 3))
    for ntid, _ord, name in src.execute("SELECT ntid, ord, name FROM fields ORDER BY ntid, ord"):
        models[ntid]["fields"].append(name)
    for ntid, _ord, name, config in src.execute("SELECT ntid, ord, name, config FROM templates ORDER BY ntid, ord"):
        cfg = pb_decode(config)
        models[ntid]["templates"].append({"name": name, "qfmt": _pb_str(cfg, 1), "afmt": _pb_str(cfg, 2)})
    decks = {did: name.replace("\x1f", "::") for did, name in src.execute("SELECT id, name FROM decks")}
    return models, decks


def _read_media_map(z: zipfile.ZipFile) -> dict[str, str]:
    """zip member name -> real filename"""
    if "media" not in z.namelist():
        return {}
    raw = z.read("media")
    try:
        return {k: v for k, v in json.loads(raw.decode("utf-8")).items()}
    except (UnicodeDecodeError, json.JSONDecodeError):
        pass
    entries = pb_decode(_unzstd(raw)).get(1, [])
    out = {}
    for idx, e in enumerate(entries):
        d = pb_decode(e)
        member = str(_pb_int(d, 255, idx)) if d.get(255) else str(idx)
        out[member] = _pb_str(d, 1)
    return out


def _safe_name(name: str) -> str | None:
    name = os.path.basename(name.replace("\\", "/"))
    return name if name and name not in (".", "..") else None


_SOURCE_FIELDS = ("source", "reference", "ref", "bear", "link", "url")
_URL = re.compile(r"""(bear://[^\s"'<>]+|https?://[^\s"'<>]+)""")


def _source_from_fields(names: list[str], vals: list[str]) -> tuple[str | None, str | None]:
    """A deck can carry its own source link: a field named Source/Reference/Bear/Link, or any bear:// URL."""
    cands = [v for n, v in zip(names, vals) if n.strip().lower() in _SOURCE_FIELDS] + \
            [v for v in vals if "bear://" in v]
    for v in cands:
        m = _URL.search(html.unescape(v))
        if m:
            url = m.group(1)
            q = parse_qs(urlparse(url).query)
            label = (q.get("header") or q.get("title") or [None])[0]
            return url, label
    return None, None


def import_apkg(path: str | Path, with_history: bool = True) -> dict:
    db.conn()  # ensures data + media dirs exist
    with zipfile.ZipFile(path) as z, tempfile.TemporaryDirectory() as tmp:
        names = set(z.namelist())
        for cand in ("collection.anki21b", "collection.anki21", "collection.anki2"):
            if cand in names:
                break
        else:
            raise ValueError("No Anki collection found inside the file")
        col_path = Path(tmp) / "col.db"
        col_path.write_bytes(_unzstd(z.read(cand)))
        src = sqlite3.connect(col_path)
        tables = {r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        models, decks = _read_models_v18(src) if "notetypes" in tables else _read_models_legacy(src)

        # media
        media_count = 0
        for member, fname in _read_media_map(z).items():
            safe = _safe_name(fname)
            if not safe or member not in names:
                continue
            target = db.MEDIA_DIR / safe
            if not target.exists():
                target.write_bytes(_unzstd(z.read(member)))
            media_count += 1

        notes = src.execute("SELECT id, guid, mid, flds, tags FROM notes").fetchall()
        cards = src.execute("SELECT id, nid, did, ord, queue, due, odid FROM cards").fetchall()
        revs = defaultdict(list)
        if with_history:
            for cid, ts, ease, ms, rtype, ivl in src.execute(
                    "SELECT cid, id, ease, time, type, ivl FROM revlog ORDER BY cid, id"):
                if 1 <= ease <= 4 and rtype in (0, 1, 2, 3):
                    revs[cid].append((ts, ease, ms))
                elif rtype == 4 and ivl == 0:  # "forget" -> card reset to new
                    revs[cid].append((ts, 0, 0))
        src.close()

    c = db.conn()
    sch = sched.scheduler()
    stats = {"notes": 0, "cards": 0, "skipped_cards": 0, "reviews": 0, "media": media_count, "decks": 0}
    with db.lock():
        c.execute("BEGIN")
        try:
            # decks: map by name so re-imports and same-named decks merge
            deck_map = {}
            used_dids = {r[2] for r in cards} | {r[6] for r in cards if r[6]}
            for did in used_dids:
                name = decks.get(did, "Default")
                row = c.execute("SELECT id FROM decks WHERE name = ?", (name,)).fetchone()
                if row:
                    deck_map[did] = row[0]
                else:
                    taken = c.execute("SELECT 1 FROM decks WHERE id = ?", (did,)).fetchone()
                    cur = c.execute("INSERT INTO decks(id, name) VALUES (?, ?)", (None if taken else did, name))
                    deck_map[did] = cur.lastrowid
                    stats["decks"] += 1
            # also create parent decks so the tree is complete
            for name in [r[0] for r in c.execute("SELECT name FROM decks")]:
                parts = name.split("::")
                for i in range(1, len(parts)):
                    c.execute("INSERT OR IGNORE INTO decks(name) VALUES (?)", ("::".join(parts[:i]),))

            for mid, m in models.items():
                c.execute("INSERT OR REPLACE INTO notetypes(id, name, kind, fields, templates, css) VALUES (?,?,?,?,?,?)",
                          (mid, m["name"], m["kind"], json.dumps(m["fields"]), json.dumps(m["templates"]), m["css"]))

            for nid, guid, mid, flds, tags in notes:
                vals = flds.split("\x1f")
                url, label = _source_from_fields(models.get(mid, {}).get("fields", []), vals)
                # upsert: keep a source link set later (e.g. by tools/bear_link.py) unless the deck provides one,
                # and never overwrite fields of a note that was edited in-app
                c.execute("""INSERT INTO notes(id, guid, notetype_id, fields, tags, source_url, source_label)
                             VALUES (?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET guid=excluded.guid,
                             notetype_id=excluded.notetype_id, tags=excluded.tags,
                             fields=CASE WHEN notes.edited_at IS NULL THEN excluded.fields ELSE notes.fields END,
                             source_url=COALESCE(excluded.source_url, notes.source_url),
                             source_label=COALESCE(excluded.source_label, notes.source_label)""",
                          (nid, guid, mid, json.dumps(vals), tags.strip(), url, label))
                stats["notes"] += 1

            existing = {r[0] for r in c.execute("SELECT id FROM cards")}
            for cid, nid, did, ord_, queue, due, odid in cards:
                if cid in existing:
                    stats["skipped_cards"] += 1  # keep local progress on re-import
                    continue
                deck_id = deck_map[odid] if odid else deck_map[did]
                row = dict(id=cid, state=0, step=None, stability=None, difficulty=None,
                           due=0, last_review=None, reps=0, lapses=0)
                logs = []
                if revs.get(cid):
                    row, logs = sched.replay(row, revs[cid], sch)
                if row["state"] == 0:
                    row["due"] = due if queue == 0 else 10**9  # new-card position
                c.execute("""INSERT INTO cards(id, note_id, deck_id, ord, state, step, stability, difficulty,
                             due, last_review, reps, lapses, suspended) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                          (cid, nid, deck_id, ord_, row["state"], row["step"], row["stability"], row["difficulty"],
                           row["due"], row["last_review"], row["reps"], row["lapses"], 1 if queue == -1 else 0))
                for lg in logs:
                    c.execute("""INSERT INTO revlog(card_id, ts, rating, state_before, state_after, stability_before,
                                 difficulty_before, stability, difficulty, retrievability, elapsed_days, interval_secs,
                                 duration_ms, imported) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                              (lg["card_id"], lg["ts"], lg["rating"], lg["state_before"], lg["state_after"],
                               lg["stability_before"], lg["difficulty_before"], lg["stability"], lg["difficulty"],
                               lg["retrievability"], lg["elapsed_days"], lg["interval_secs"], lg["duration_ms"], 1))
                stats["reviews"] += len(logs)
                stats["cards"] += 1
            c.execute("COMMIT")
        except Exception:
            c.execute("ROLLBACK")
            raise
    return stats


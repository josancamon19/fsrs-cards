import asyncio
import hashlib
import hmac
import json
import math
import os
import re
import shutil
import tempfile
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.gzip import GZipMiddleware
from pydantic import BaseModel

from . import apkg, db, render, responses, sched

STATIC = Path(__file__).resolve().parent.parent / "static"
CARD_COLS = ("state", "step", "stability", "difficulty", "due", "last_review", "reps", "lapses")

app = FastAPI(title="FSRS Cards")
app.add_middleware(GZipMiddleware, minimum_size=2048)
app.mount("/static", StaticFiles(directory=STATIC), name="static")
db.conn()
responses.resume_pending()

# ---------------------------------------------------------------- auth (single user)
# Set APP_PASSWORD to require a login (always do this when deployed). Unset = open (local use).
PASSWORD = os.environ.get("APP_PASSWORD", "")
SECRET = (os.environ.get("SECRET_KEY") or hashlib.sha256(("fsrs-cards:" + PASSWORD).encode()).hexdigest()).encode()
COOKIE = "fsrs_session"
PUBLIC = ("/static/", "/healthz", "/sw.js", "/manifest.webmanifest", "/api/login", "/api/session", "/favicon")


def _token() -> str:
    # bound to the password: changing APP_PASSWORD logs out every device
    return hmac.new(SECRET, b"session:" + hashlib.sha256(PASSWORD.encode()).digest(), hashlib.sha256).hexdigest()


def authed(request: Request) -> bool:
    return not PASSWORD or hmac.compare_digest(request.cookies.get(COOKIE, ""), _token())


@app.middleware("http")
async def require_login(request: Request, call_next):
    path = request.url.path
    if PASSWORD and path != "/" and not path.startswith(PUBLIC) and not authed(request):
        return JSONResponse({"detail": "login required"}, status_code=401)
    return await call_next(request)


class Login(BaseModel):
    password: str


@app.post("/api/login")
async def login(body: Login):
    if not PASSWORD or hmac.compare_digest(body.password.encode(), PASSWORD.encode()):
        resp = JSONResponse({"ok": True})
        resp.set_cookie(COOKIE, _token(), max_age=400 * 86400, httponly=True, samesite="lax",
                        secure=os.environ.get("FLY_APP_NAME") is not None)
        return resp
    await asyncio.sleep(1.0)  # slow down guessing
    raise HTTPException(401, "Wrong password")


@app.get("/api/session")
def session(request: Request):
    return {"authed": authed(request), "auth_required": bool(PASSWORD)}


@app.post("/api/logout")
def logout():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(COOKIE)
    return resp


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


@app.get("/", response_class=HTMLResponse)
def index():
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/sw.js")
def service_worker():
    return FileResponse(STATIC / "sw.js", media_type="text/javascript",
                        headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"})


@app.get("/manifest.webmanifest")
def manifest():
    return FileResponse(STATIC / "manifest.webmanifest", media_type="application/manifest+json")


@app.get("/healthz")
def healthz():
    db.conn().execute("SELECT 1")
    return {"ok": True}


@app.get("/media/{name:path}")
def media(name: str):
    p = (db.MEDIA_DIR / Path(name).name)
    if not p.is_file():
        raise HTTPException(404)
    return FileResponse(p, headers={"Cache-Control": "private, max-age=31536000, immutable"})


# ---------------------------------------------------------------- decks

@app.get("/api/decks")
def decks():
    c = db.conn()
    s = db.get_settings()
    now = now_utc()
    rows = c.execute("SELECT id, name FROM decks ORDER BY name COLLATE NOCASE").fetchall()
    totals = {r[0]: r[1] for r in c.execute("SELECT deck_id, COUNT(*) FROM cards GROUP BY deck_id")}
    out = []
    for r in rows:
        ids = sched.deck_ids(r["name"])
        cnt = sched.counts(ids, now, s)
        total = sum(totals.get(i, 0) for i in ids)
        out.append({"id": r["id"], "name": r["name"], "depth": r["name"].count("::"),
                    "short": r["name"].split("::")[-1], "total": total,
                    "new": cnt["new"], "learning": cnt["learning"], "review": cnt["review"]})
    return [d for d in out if d["total"] > 0]


# Destructive/bulk operations (import, deck deletion) need ADMIN_TOKEN as an X-Admin-Token header on top of the
# login, so they can only be run from code on your machine (tools/import_apkg.py), never from the website.
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")


def require_admin(request: Request):
    if PASSWORD and not ADMIN_TOKEN:
        raise HTTPException(403, "Disabled: set ADMIN_TOKEN on the server to allow this from code")
    if ADMIN_TOKEN and not hmac.compare_digest(request.headers.get("x-admin-token", ""), ADMIN_TOKEN):
        raise HTTPException(403, "Admin token required (use tools/import_apkg.py)")


@app.delete("/api/decks/{deck_id}")
def delete_deck(deck_id: int, request: Request):
    require_admin(request)
    c = db.conn()
    row = c.execute("SELECT name FROM decks WHERE id = ?", (deck_id,)).fetchone()
    if not row:
        raise HTTPException(404)
    ids = sched.deck_ids(row["name"])
    ind = sched._in(ids)
    with db.lock():
        c.execute("BEGIN")
        c.execute(f"DELETE FROM revlog WHERE card_id IN (SELECT id FROM cards WHERE deck_id IN {ind})")
        c.execute(f"DELETE FROM cards WHERE deck_id IN {ind}")
        c.execute("DELETE FROM notes WHERE id NOT IN (SELECT note_id FROM cards)")
        c.execute(f"DELETE FROM decks WHERE id IN {ind}")
        c.execute("COMMIT")
    return {"ok": True}


@app.post("/api/import")
async def import_file(request: Request, file: UploadFile = File(...), history: bool = Form(True)):
    require_admin(request)
    with tempfile.NamedTemporaryFile(suffix=".apkg", delete=False) as tmp:
        shutil.copyfileobj(file.file, tmp)
        path = tmp.name
    t0 = time.perf_counter()
    try:
        stats = apkg.import_apkg(path, with_history=history)
    except Exception as e:  # surface parse errors to the UI
        raise HTTPException(400, f"Import failed: {e}")
    finally:
        Path(path).unlink(missing_ok=True)
    render.clear_cache()
    stats["seconds"] = round(time.perf_counter() - t0, 2)
    return stats


# ---------------------------------------------------------------- study

def card_payload(row, now: datetime) -> dict:
    sch = sched.scheduler()
    r = render.render_card(row)
    now_ts = int(now.timestamp())
    r.update(
        id=row["id"], state=sched.STATE_NAMES[row["state"]], stability=row["stability"],
        difficulty=row["difficulty"], reps=row["reps"], lapses=row["lapses"], due=row["due"],
        last_review=row["last_review"],
        retrievability=sched.retrievability(sch, row["stability"], row["last_review"], now_ts),
        elapsed_days=(now_ts - row["last_review"]) / 86400 if row["last_review"] else None,
        previews=sched.preview(row, now),
    )
    return r


def skip_list(skip: str | list[int] | None) -> list[int]:
    if isinstance(skip, str):
        skip = [int(x) for x in skip.split(",") if x.strip().isdigit()]
    return list(skip or [])[-200:]


def study_state(deck: str | None, exclude: list[int] | None = None):
    s = db.get_settings()
    now = now_utc()
    ids = sched.deck_ids(deck)
    row, cnt = sched.next_card(ids, now, s, exclude)
    res = {"counts": cnt}
    if row is None:
        res["done"] = True
        res["next_learning_due"] = sched.next_learning_due(ids)
    else:
        res["card"] = card_payload(row, now)
    return res


@app.get("/api/study/next")
def study_next(deck: str | None = None, skip: str | None = None):
    """`skip`: comma-separated card ids skipped this session (oldest first). Skipping writes no review."""
    return study_state(deck, skip_list(skip))


@app.get("/api/study/card/{card_id}")
def study_card(card_id: int, deck: str | None = None):
    """Show a specific card in the study view (used when undoing a suspend)."""
    row = db.conn().execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()
    if not row:
        raise HTTPException(404)
    now = now_utc()
    return {"counts": sched.counts(sched.deck_ids(deck), now, db.get_settings()), "card": card_payload(row, now)}


class Answer(BaseModel):
    card_id: int
    rating: int
    duration_ms: int = 0
    deck: str | None = None
    skip: list[int] = []            # cards skipped this session, oldest first


@app.post("/api/study/answer")
def study_answer(a: Answer):
    if a.rating not in (1, 2, 3, 4):
        raise HTTPException(400, "rating must be 1..4")
    c = db.conn()
    now = now_utc()
    with db.lock():
        row = c.execute("SELECT * FROM cards WHERE id = ?", (a.card_id,)).fetchone()
        if not row:
            raise HTTPException(404)
        cols, log = sched.apply_review(row, a.rating, now)
        prev = json.dumps({k: row[k] for k in CARD_COLS})
        c.execute("BEGIN")
        c.execute(f"UPDATE cards SET {', '.join(k + ' = ?' for k in cols)} WHERE id = ?", (*cols.values(), a.card_id))
        c.execute("""INSERT INTO revlog(card_id, ts, rating, state_before, state_after, stability_before,
                     difficulty_before, stability, difficulty, retrievability, elapsed_days, interval_secs,
                     duration_ms, prev) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                  (a.card_id, int(now.timestamp() * 1000), log["rating"], log["state_before"], log["state_after"],
                   log["stability_before"], log["difficulty_before"], log["stability"], log["difficulty"],
                   log["retrievability"], log["elapsed_days"], log["interval_secs"],
                   min(a.duration_ms, 600_000), prev))
        c.execute("COMMIT")
    res = study_state(a.deck, exclude=[x for x in skip_list(a.skip) if x != a.card_id] + [a.card_id])
    res["answered"] = {"card_id": a.card_id, "rating": a.rating, "interval_secs": log["interval_secs"],
                       "stability": log["stability"], "difficulty": log["difficulty"],
                       "stability_before": log["stability_before"], "retrievability": log["retrievability"]}
    return res


class Undo(BaseModel):
    deck: str | None = None


@app.post("/api/study/undo")
def study_undo(u: Undo):
    c = db.conn()
    with db.lock():
        lg = c.execute("SELECT * FROM revlog WHERE imported = 0 AND prev IS NOT NULL ORDER BY id DESC LIMIT 1").fetchone()
        if not lg:
            raise HTTPException(404, "Nothing to undo")
        prev = json.loads(lg["prev"])
        c.execute("BEGIN")
        c.execute(f"UPDATE cards SET {', '.join(k + ' = ?' for k in prev)} WHERE id = ?", (*prev.values(), lg["card_id"]))
        c.execute("DELETE FROM revlog WHERE id = ?", (lg["id"],))
        c.execute("COMMIT")
        row = c.execute("SELECT * FROM cards WHERE id = ?", (lg["card_id"],)).fetchone()
    s = db.get_settings()
    now = now_utc()
    return {"counts": sched.counts(sched.deck_ids(u.deck), now, s), "card": card_payload(row, now),
            "undone_rating": lg["rating"]}


# ---------------------------------------------------------------- cards

@app.get("/api/cards/{card_id}")
def card_info(card_id: int):
    c = db.conn()
    row = c.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()
    if not row:
        raise HTTPException(404)
    now = now_utc()
    p = card_payload(row, now)
    p["suspended"] = bool(row["suspended"])
    p["suspended_at"] = row["suspended_at"]
    p["suspend_reason"] = row["suspend_reason"]
    p["responses"] = [responses.to_dict(r) for r in c.execute(
        "SELECT * FROM responses WHERE card_id = ? ORDER BY ts DESC", (card_id,))]
    p["history"] = [dict(r) for r in c.execute(
        """SELECT ts, rating, state_before, state_after, stability_before, stability, difficulty, retrievability,
                  elapsed_days, interval_secs, duration_ms, imported FROM revlog WHERE card_id = ? ORDER BY ts""",
        (card_id,))]
    # forgetting curve from the current stability
    sch = sched.scheduler()
    if row["stability"]:
        span = max(30, min(3650, row["stability"] * 3))
        p["curve"] = [[d, (1 + sch._FACTOR * d / row["stability"]) ** sch._DECAY]
                      for d in [span * i / 60 for i in range(61)]]
    return p


class Suspend(BaseModel):
    suspended: bool | None = None  # None = toggle
    reason: str | None = None


@app.post("/api/cards/{card_id}/suspend")
def card_suspend(card_id: int, body: Suspend | None = None):
    """Suspending records when and why, so suspended cards form a rewrite queue (see /api/suspended)."""
    c = db.conn()
    body = body or Suspend()
    with db.lock():
        row = c.execute("SELECT suspended FROM cards WHERE id = ?", (card_id,)).fetchone()
        if not row:
            raise HTTPException(404)
        on = (not row[0]) if body.suspended is None else body.suspended
        if on:
            c.execute("UPDATE cards SET suspended = 1, suspended_at = COALESCE(CASE WHEN suspended = 1 THEN suspended_at END, ?),"
                      " suspend_reason = COALESCE(?, suspend_reason) WHERE id = ?",
                      (int(time.time()), (body.reason or "").strip() or None, card_id))
        else:
            c.execute("UPDATE cards SET suspended = 0, suspended_at = NULL, suspend_reason = NULL WHERE id = ?", (card_id,))
    return {"suspended": on}


@app.get("/api/suspended")
def suspended_cards(deck: str | None = None):
    """The rewrite queue: every suspended card with its text, reason, FSRS history and Bear link."""
    c = db.conn()
    where = f"AND c.deck_id IN {sched._in(sched.deck_ids(deck))}" if deck else ""
    rows = c.execute(f"""SELECT c.*, n.fields AS nfields, n.tags, n.source_url, n.source_label, t.fields AS names,
                                t.name AS notetype, d.name AS deck FROM cards c JOIN notes n ON n.id = c.note_id
                         JOIN notetypes t ON t.id = n.notetype_id LEFT JOIN decks d ON d.id = c.deck_id
                         WHERE c.suspended = 1 {where} ORDER BY c.suspended_at IS NULL, c.suspended_at DESC""").fetchall()
    out = []
    for r in rows:
        fields = dict(zip(json.loads(r["names"]), json.loads(r["nfields"])))
        again = c.execute("SELECT COUNT(*), SUM(rating = 1) FROM revlog WHERE card_id = ?", (r["id"],)).fetchone()
        out.append({"card_id": r["id"], "note_id": r["note_id"], "deck": r["deck"], "notetype": r["notetype"],
                    "suspended_at": r["suspended_at"], "reason": r["suspend_reason"],
                    "fields": {k: render.strip_html(render.CLOZE_TEXT.sub(r"\1", v)) for k, v in fields.items()},
                    "fields_html": fields, "tags": r["tags"],
                    "reviews": again[0], "again_count": again[1] or 0, "lapses": r["lapses"],
                    "difficulty": r["difficulty"], "stability": r["stability"],
                    "source_url": r["source_url"], "source_label": r["source_label"]})
    return out


@app.post("/api/cards/{card_id}/reset")
def card_reset(card_id: int):
    c = db.conn()
    with db.lock():
        c.execute("""UPDATE cards SET state = 0, step = NULL, stability = NULL, difficulty = NULL, last_review = NULL,
                     reps = 0, lapses = 0 WHERE id = ?""", (card_id,))
    return {"ok": True}


@app.get("/api/browse")
def browse(q: str = "", deck: str | None = None, state: str | None = None, sort: str = "due",
           limit: int = 100, offset: int = 0):
    c = db.conn()
    where, args = ["1=1"], []
    if deck:
        where.append(f"c.deck_id IN {sched._in(sched.deck_ids(deck))}")
    if state == "suspended":
        where.append("c.suspended = 1")
    elif state in ("new", "learning", "review", "relearning"):
        where.append("c.state = ?")
        args.append({v: k for k, v in sched.STATE_NAMES.items()}[state])
    if q:
        where.append("(n.fields LIKE ? OR n.tags LIKE ?)")
        args += [f"%{q}%", f"%{q}%"]
    order = {"due": "c.state = 0, c.due", "stability": "c.stability IS NULL, c.stability DESC",
             "difficulty": "c.difficulty IS NULL, c.difficulty DESC", "lapses": "c.lapses DESC",
             "reps": "c.reps DESC", "added": "c.id DESC"}.get(sort, "c.due")
    w = " AND ".join(where)
    total = c.execute(f"SELECT COUNT(*) FROM cards c JOIN notes n ON n.id = c.note_id WHERE {w}", args).fetchone()[0]
    rows = c.execute(f"""SELECT c.*, n.fields AS nfields, n.tags, d.name AS deck FROM cards c
                         JOIN notes n ON n.id = c.note_id LEFT JOIN decks d ON d.id = c.deck_id
                         WHERE {w} ORDER BY {order} LIMIT ? OFFSET ?""", (*args, min(limit, 500), offset)).fetchall()
    sch = sched.scheduler()
    now_ts = int(time.time())
    items = []
    for r in rows:
        f = [render.CLOZE_TEXT.sub(r"\1", x) for x in json.loads(r["nfields"])]
        items.append({
            "id": r["id"], "front": render.strip_html(f[0])[:140] if f else "",
            "back": render.strip_html(f[1])[:140] if len(f) > 1 else "",
            "deck": r["deck"], "state": sched.STATE_NAMES[r["state"]], "suspended": bool(r["suspended"]),
            "suspend_reason": r["suspend_reason"],
            "due": r["due"] if r["state"] else None, "stability": r["stability"], "difficulty": r["difficulty"],
            "retrievability": sched.retrievability(sch, r["stability"], r["last_review"], now_ts),
            "reps": r["reps"], "lapses": r["lapses"], "tags": r["tags"]})
    return {"total": total, "items": items}


@app.get("/api/notetypes")
def notetypes():
    rows = db.conn().execute("SELECT id, name, kind, fields, templates FROM notetypes ORDER BY name").fetchall()
    return [{"id": r["id"], "name": r["name"], "cloze": r["kind"] == 1, "fields": json.loads(r["fields"]),
             "templates": [t["name"] for t in json.loads(r["templates"])]} for r in rows]


def note_dict(n, names, cards) -> dict:
    return {"id": n["id"], "notetype": n["notetype"], "deck": cards[0]["deck"] if cards else None, "tags": n["tags"],
            "fields": dict(zip(names, json.loads(n["fields"]))), "source_url": n["source_url"],
            "source_label": n["source_label"], "edited_at": n["edited_at"],
            "cards": [{"id": c["id"], "ord": c["ord"], "state": sched.STATE_NAMES[c["state"]], "suspended": bool(c["suspended"]),
                       "suspend_reason": c["suspend_reason"], "reps": c["reps"], "lapses": c["lapses"]} for c in cards]}


@app.get("/api/notes")
def list_notes(deck: str | None = None, q: str = ""):
    """Every note with named fields, deck and card states (used by tools/cards.py and tools/bear_link.py)."""
    c = db.conn()
    where, args = [f"c.deck_id IN {sched._in(sched.deck_ids(deck))}"], []
    if q:
        where.append("(n.fields LIKE ? OR n.tags LIKE ?)")
        args += [f"%{q}%", f"%{q}%"]
    rows = c.execute(f"""SELECT c.id, c.note_id, c.ord, c.state, c.suspended, c.suspend_reason, c.reps, c.lapses,
                                d.name AS deck FROM cards c JOIN notes n ON n.id = c.note_id JOIN decks d ON d.id = c.deck_id
                         WHERE {' AND '.join(where)} ORDER BY d.name, c.note_id, c.ord""", args).fetchall()
    by_note = defaultdict(list)
    for r in rows:
        by_note[r["note_id"]].append(r)
    if not by_note:
        return []
    notes = c.execute(f"""SELECT n.*, t.name AS notetype, t.fields AS names FROM notes n JOIN notetypes t ON t.id = n.notetype_id
                          WHERE n.id IN ({','.join('?' * len(by_note))})""", list(by_note)).fetchall()
    order = {nid: i for i, nid in enumerate(by_note)}
    return sorted((note_dict(n, json.loads(n["names"]), by_note[n["id"]]) for n in notes), key=lambda d: order[d["id"]])


def get_note(note_id: int) -> dict:
    c = db.conn()
    n = c.execute("""SELECT n.*, t.name AS notetype, t.fields AS names FROM notes n JOIN notetypes t ON t.id = n.notetype_id
                     WHERE n.id = ?""", (note_id,)).fetchone()
    if not n:
        raise HTTPException(404, f"note {note_id} not found")
    cards = c.execute("""SELECT c.*, d.name AS deck FROM cards c JOIN decks d ON d.id = c.deck_id
                         WHERE c.note_id = ? ORDER BY c.ord""", (note_id,)).fetchall()
    return note_dict(n, json.loads(n["names"]), cards)


@app.get("/api/notes/{note_id}")
def read_note(note_id: int):
    return get_note(note_id)


class NoteNew(BaseModel):
    notetype: str | int             # name or id, e.g. "Math4ML · Basic"
    deck: str                       # full deck name; created if it doesn't exist
    fields: dict[str, str]
    tags: str = ""
    source_url: str | None = None
    source_label: str | None = None


@app.post("/api/notes")
def create_note(body: NoteNew):
    """Add a note and its cards (one per template, or one per cloze number) as new cards at the end of the queue."""
    c = db.conn()
    nt = c.execute("SELECT * FROM notetypes WHERE id = ? OR name = ?", (body.notetype, str(body.notetype))).fetchone()
    if not nt:
        raise HTTPException(400, f"unknown note type {body.notetype!r}; see /api/notetypes")
    names = json.loads(nt["fields"])
    unknown = set(body.fields) - set(names)
    if unknown:
        raise HTTPException(400, f"unknown fields {sorted(unknown)}; {nt['name']} has {names}")
    vals = [body.fields.get(k, "") for k in names]
    if nt["kind"] == 1:
        ords = sorted({int(m) - 1 for v in vals for m in re.findall(r"\{\{c(\d+)::", v)})
        if not ords:
            raise HTTPException(400, "a cloze note needs at least one {{c1::...}}")
    else:
        ords = list(range(len(json.loads(nt["templates"]))))
    with db.lock():
        c.execute("BEGIN")
        try:
            for i, part in enumerate(body.deck.split("::")):  # deck and its parents
                c.execute("INSERT OR IGNORE INTO decks(name) VALUES (?)", ("::".join(body.deck.split("::")[:i + 1]),))
            deck_id = c.execute("SELECT id FROM decks WHERE name = ?", (body.deck,)).fetchone()[0]
            nid = max(int(time.time() * 1000), (c.execute("SELECT MAX(id) FROM notes").fetchone()[0] or 0) + 1,
                      (c.execute("SELECT MAX(id) FROM cards").fetchone()[0] or 0) + 1)
            c.execute("""INSERT INTO notes(id, guid, notetype_id, fields, tags, source_url, source_label, edited_at)
                         VALUES (?,?,?,?,?,?,?,?)""", (nid, f"fsrs-{nid}", nt["id"], json.dumps(vals), body.tags.strip(),
                                                       body.source_url, body.source_label, int(time.time())))
            pos = (c.execute("SELECT MAX(due) FROM cards WHERE state = 0 AND due < 1000000000").fetchone()[0] or 0) + 1
            for k, o in enumerate(ords):
                c.execute("INSERT INTO cards(id, note_id, deck_id, ord, due) VALUES (?,?,?,?,?)", (nid + 1 + k, nid, deck_id, o, pos))
            c.execute("COMMIT")
        except Exception:
            c.execute("ROLLBACK")
            raise
    return get_note(nid)


class NoteEdit(BaseModel):
    fields: dict[str, str] = {}     # field name -> new HTML value (only the fields you want to change)
    tags: str | None = None
    deck: str | None = None         # move the note's cards to this deck (created if missing)
    reset_cards: bool = False       # the question changed, so the old memory state no longer applies


@app.put("/api/notes/{note_id}")
def edit_note(note_id: int, body: NoteEdit):
    c = db.conn()
    row = c.execute("""SELECT n.fields, t.fields AS names FROM notes n JOIN notetypes t ON t.id = n.notetype_id
                       WHERE n.id = ?""", (note_id,)).fetchone()
    if not row:
        raise HTTPException(404)
    names, vals = json.loads(row["names"]), json.loads(row["fields"])
    vals += [""] * (len(names) - len(vals))
    unknown = set(body.fields) - set(names)
    if unknown:
        raise HTTPException(400, f"unknown fields {sorted(unknown)}; this note type has {names}")
    for k, v in body.fields.items():
        vals[names.index(k)] = v
    with db.lock():
        c.execute("BEGIN")
        c.execute("UPDATE notes SET fields = ?, edited_at = ? WHERE id = ?", (json.dumps(vals), int(time.time()), note_id))
        if body.tags is not None:
            c.execute("UPDATE notes SET tags = ? WHERE id = ?", (body.tags.strip(), note_id))
        if body.deck:
            for i in range(len(body.deck.split("::"))):
                c.execute("INSERT OR IGNORE INTO decks(name) VALUES (?)", ("::".join(body.deck.split("::")[:i + 1]),))
            c.execute("UPDATE cards SET deck_id = (SELECT id FROM decks WHERE name = ?) WHERE note_id = ?", (body.deck, note_id))
        if body.reset_cards:
            c.execute("""UPDATE cards SET state = 0, step = NULL, stability = NULL, difficulty = NULL, last_review = NULL,
                         reps = 0, lapses = 0, due = 0 WHERE note_id = ?""", (note_id,))
        c.execute("COMMIT")
    render.clear_cache()
    return get_note(note_id)


@app.delete("/api/notes/{note_id}")
def delete_note(note_id: int, request: Request):
    """Delete a note, its cards and their review history. Spoken answers are kept (they hold their own text)."""
    require_admin(request)  # irreversible: deletes review history
    c = db.conn()
    with db.lock():
        c.execute("BEGIN")
        c.execute("DELETE FROM revlog WHERE card_id IN (SELECT id FROM cards WHERE note_id = ?)", (note_id,))
        n = c.execute("DELETE FROM cards WHERE note_id = ?", (note_id,)).rowcount
        c.execute("DELETE FROM notes WHERE id = ?", (note_id,))
        c.execute("COMMIT")
    return {"deleted_cards": n}


class Sources(BaseModel):
    sources: dict[int, dict]  # note_id -> {"url": ..., "label": ...}


@app.post("/api/notes/sources")
def set_sources(body: Sources):
    c = db.conn()
    with db.lock():
        c.execute("BEGIN")
        n = 0
        for nid, src in body.sources.items():
            n += c.execute("UPDATE notes SET source_url = ?, source_label = ? WHERE id = ?",
                           (src.get("url"), src.get("label"), nid)).rowcount
        c.execute("COMMIT")
    return {"updated": n}


# ---------------------------------------------------------------- spoken answers

@app.post("/api/cards/{card_id}/responses")
async def upload_response(card_id: int, audio: UploadFile | None = File(None), audio_after: UploadFile | None = File(None),
                          ts: int = Form(...),
                          duration_ms: int | None = Form(None), reveal_ms: int | None = Form(None),
                          rating: int | None = Form(None), flagged: bool = Form(False)):
    """Store a recording for background transcription. The audio is deleted as soon as it is transcribed.
    `audio` is the recall attempt (until the card was flipped) and `audio_after` what was said after; either may be missing."""
    if not db.conn().execute("SELECT 1 FROM cards WHERE id = ?", (card_id,)).fetchone():
        raise HTTPException(404)
    parts = []
    for f in (audio, audio_after):
        data = await f.read() if f else b""
        if len(data) > 25 * 1024 * 1024:
            raise HTTPException(413, "Recording is over OpenAI's 25 MB limit")
        parts.append((data, f.content_type or "audio/webm") if data else None)
    if not any(parts):
        raise HTTPException(400, "no audio")
    rid = await asyncio.to_thread(responses.save_upload, card_id, *parts, ts=ts,
                                  duration_ms=duration_ms, reveal_ms=reveal_ms, rating=rating, flagged=flagged)
    return {"id": rid, "status": "pending", "transcription": bool(responses.api_key())}


@app.get("/api/responses")
def list_responses(card_id: int | None = None, ids: str | None = None, flagged: bool | None = None,
                   gaps: bool | None = None, q: str = "", deck: str | None = None, limit: int = 100, offset: int = 0):
    """Spoken answers, newest first. `ids=1,2,3` is used to poll pending ones."""
    where, args = ["1=1"], []
    if card_id is not None:
        where.append("r.card_id = ?")
        args.append(card_id)
    if ids:
        id_list = [int(x) for x in ids.split(",") if x.strip().isdigit()][:200]
        where.append(f"r.id IN ({','.join('?' * len(id_list)) or 'NULL'})")
        args += id_list
    if flagged is not None:
        where.append("r.flagged = ?")
        args.append(int(flagged))
    if gaps:
        where.append("(r.flagged = 1 OR json_array_length(r.analysis, '$.unsure') > 0)")
    if q:
        where.append("(r.transcript LIKE ? OR r.transcript_after LIKE ? OR r.question LIKE ? OR r.note LIKE ?)")
        args += [f"%{q}%"] * 4
    if deck:
        where.append(f"c.deck_id IN {sched._in(sched.deck_ids(deck))}")
    w = " AND ".join(where)
    c = db.conn()
    base = f"FROM responses r LEFT JOIN cards c ON c.id = r.card_id LEFT JOIN decks d ON d.id = c.deck_id WHERE {w}"
    total = c.execute(f"SELECT COUNT(*) {base}", args).fetchone()[0]
    rows = c.execute(f"SELECT r.*, d.name AS deck {base} ORDER BY r.ts DESC LIMIT ? OFFSET ?",
                     (*args, min(limit, 500), offset)).fetchall()
    attempts = {}
    if rows:  # how many spoken answers each card has, so the list can say "3rd attempt"
        cids = {r["card_id"] for r in rows}
        attempts = dict(c.execute(f"SELECT card_id, COUNT(*) FROM responses WHERE card_id IN ({','.join('?' * len(cids))})"
                                  " GROUP BY card_id", list(cids)).fetchall())
    return {"total": total, "configured": bool(responses.api_key()),
            "items": [{**responses.to_dict(r), "deck": r["deck"], "attempts": attempts.get(r["card_id"], 1)} for r in rows]}


class ResponseEdit(BaseModel):
    flagged: bool | None = None
    note: str | None = None


@app.patch("/api/responses/{rid}")
def edit_response(rid: int, body: ResponseEdit):
    cols = {k: v for k, v in (("flagged", body.flagged), ("note", body.note)) if v is not None}
    if cols:
        with db.lock():
            db.conn().execute(f"UPDATE responses SET {', '.join(k + ' = ?' for k in cols)} WHERE id = ?", (*cols.values(), rid))
    row = db.conn().execute("SELECT * FROM responses WHERE id = ?", (rid,)).fetchone()
    if not row:
        raise HTTPException(404)
    return responses.to_dict(row)


@app.post("/api/responses/{rid}/retry")
def retry_response(rid: int):
    with db.lock():
        n = db.conn().execute("UPDATE responses SET status = 'pending', error = NULL WHERE id = ? AND status = 'error'",
                              (rid,)).rowcount
    if n:
        responses.enqueue(rid)
    return {"queued": bool(n)}


@app.delete("/api/responses/{rid}")
def delete_response(rid: int):
    c = db.conn()
    with db.lock():
        row = c.execute("SELECT audio_path, audio_after_path FROM responses WHERE id = ?", (rid,)).fetchone()
        for name in (row or {}) and (row["audio_path"], row["audio_after_path"]):
            if name:
                (responses.AUDIO_DIR / name).unlink(missing_ok=True)
        c.execute("DELETE FROM responses WHERE id = ?", (rid,))
    return {"ok": True}


# ---------------------------------------------------------------- stats

@app.get("/api/stats")
def stats(deck: str | None = None, days: int = 30):
    c = db.conn()
    s = db.get_settings()
    sch = sched.scheduler(s)
    now = now_utc()
    now_ts = int(now.timestamp())
    ids = sched.deck_ids(deck)
    ind = sched._in(ids)
    ds = sched.day_start(now, s["day_rollover_hour"])
    ds_ts = int(ds.timestamp())

    def day_of(ts_s):
        return math.floor((ts_s - ds_ts) / 86400)

    # card states
    st = c.execute(f"""SELECT SUM(state=0 AND suspended=0), SUM(state=1 AND suspended=0), SUM(state=2 AND suspended=0),
                       SUM(state=3 AND suspended=0), SUM(suspended), SUM(state=2 AND stability>=21 AND suspended=0), COUNT(*)
                       FROM cards WHERE deck_id IN {ind}""").fetchone()
    states = dict(zip(("new", "learning", "review", "relearning", "suspended", "mature", "total"), [x or 0 for x in st]))

    cards = c.execute(f"""SELECT state, stability, difficulty, due, last_review FROM cards
                          WHERE deck_id IN {ind} AND suspended = 0 AND state != 0""").fetchall()
    stab_bins = [0, 1, 2, 3, 5, 7, 10, 14, 21, 30, 45, 60, 90, 120, 180, 270, 365, 540, 730, 1095, 1e9]
    stab_hist = [0] * (len(stab_bins) - 1)
    diff_hist = [0] * 10
    r_hist = [0] * 20
    forecast = [0] * 31
    r_sum = r_n = 0
    for r in cards:
        if r["stability"] is not None:
            for i in range(len(stab_bins) - 1):
                if r["stability"] < stab_bins[i + 1]:
                    stab_hist[i] += 1
                    break
        if r["difficulty"] is not None:
            diff_hist[min(9, max(0, int(r["difficulty"] - 1)))] += 1
        rv = sched.retrievability(sch, r["stability"], r["last_review"], now_ts)
        if rv is not None:
            r_hist[min(19, int(rv * 20))] += 1
            r_sum += rv
            r_n += 1
        d = max(0, day_of(r["due"]))
        if d <= 30:
            forecast[d] += 1

    # review log
    since_ms = (ds_ts - (days - 1) * 86400) * 1000
    logs = c.execute(f"""SELECT r.ts, r.rating, r.state_before, r.retrievability, r.duration_ms, r.imported
                         FROM revlog r JOIN cards c ON c.id = r.card_id WHERE c.deck_id IN {ind}""").fetchall()
    daily = defaultdict(lambda: [0, 0, 0, 0, 0, 0, 0])  # again hard good easy time_ms rev_total rev_pass
    heat = defaultdict(int)
    by_state = [[0, 0, 0, 0] for _ in range(4)]
    by_hour = [[0, 0] for _ in range(24)]
    calib = defaultdict(lambda: [0.0, 0, 0])  # sum_pred, n, pass
    tot_time = 0
    tz_off = datetime.now().astimezone().utcoffset().total_seconds()
    for lg in logs:
        ts_s = lg["ts"] / 1000
        d = day_of(ts_s)
        heat[d] += 1
        if lg["ts"] >= since_ms:
            row = daily[d]
            row[lg["rating"] - 1] += 1
            row[4] += lg["duration_ms"] or 0
            if lg["state_before"] == 2:
                row[5] += 1
                row[6] += lg["rating"] > 1
            by_state[lg["state_before"]][lg["rating"] - 1] += 1
            by_hour[int(((ts_s + tz_off) % 86400) // 3600)][0] += 1
            by_hour[int(((ts_s + tz_off) % 86400) // 3600)][1] += lg["rating"] > 1
        if lg["retrievability"] is not None and lg["state_before"] == 2:
            b = min(19, int(lg["retrievability"] * 20))
            cb = calib[b]
            cb[0] += lg["retrievability"]
            cb[1] += 1
            cb[2] += lg["rating"] > 1
        tot_time += lg["duration_ms"] or 0

    series = []
    for d in range(-(days - 1), 1):
        a, h, g, e, t, rt, rp = daily[d] if d in daily else [0] * 7
        series.append({"day": d, "date": (ds_ts + d * 86400), "again": a, "hard": h, "good": g, "easy": e,
                       "time_ms": t, "retention": (rp / rt) if rt else None, "review_n": rt})
    today = series[-1]
    tr = [x for x in series if x["review_n"]]
    true_ret = (sum(x["retention"] * x["review_n"] for x in tr) / sum(x["review_n"] for x in tr)) if tr else None

    streak = 0
    d = 0 if heat.get(0) else -1
    while heat.get(d):
        streak += 1
        d -= 1

    return {
        "states": states,
        "today": {**today, "count": today["again"] + today["hard"] + today["good"] + today["easy"]},
        "series": series,
        "forecast": forecast,
        "stability_hist": [{"lo": stab_bins[i], "hi": stab_bins[i + 1], "n": n} for i, n in enumerate(stab_hist)],
        "difficulty_hist": diff_hist,
        "retrievability_hist": r_hist,
        "avg_retrievability": (r_sum / r_n) if r_n else None,
        "known_estimate": r_sum,
        "true_retention": true_ret,
        "by_state": {sched.STATE_NAMES[i]: v for i, v in enumerate(by_state)},
        "by_hour": by_hour,
        "calibration": [{"bin": b, "pred": v[0] / v[1], "actual": v[2] / v[1], "n": v[1]} for b, v in sorted(calib.items())],
        "heatmap": [[d, n] for d, n in sorted(heat.items()) if d > -371],
        "day_start": ds_ts,
        "total_reviews": len(logs),
        "total_time_ms": tot_time,
        "streak": streak,
        "fsrs": {"parameters": list(sch.parameters), "desired_retention": sch.desired_retention,
                 "decay": -sch._DECAY if sch._DECAY < 0 else sch._DECAY, "factor": sch._FACTOR},
    }


# ---------------------------------------------------------------- settings

@app.get("/api/settings")
def get_settings():
    s = db.get_settings()
    s["effective_parameters"] = list(sched.scheduler(s).parameters)
    return s


@app.post("/api/settings")
def set_settings(values: dict):
    values.pop("effective_parameters", None)
    if "parameters" in values and values["parameters"]:
        if len(values["parameters"]) != 21:
            raise HTTPException(400, "FSRS-6 needs exactly 21 parameters")
    if "desired_retention" in values and not 0.7 <= float(values["desired_retention"]) <= 0.99:
        raise HTTPException(400, "desired retention must be between 0.70 and 0.99")
    try:
        trial = {**db.get_settings(), **values}
        sched.scheduler(trial)
    except Exception as e:
        raise HTTPException(400, str(e))
    db.save_settings(values)
    return get_settings()


@app.post("/api/optimize")
def optimize():
    """Fit FSRS parameters to your own review history (needs torch: `uv sync --extra optimizer`)."""
    try:
        from fsrs import Optimizer, ReviewLog, Rating
    except ImportError as e:
        raise HTTPException(400, f"Optimizer unavailable: {e}")
    c = db.conn()
    logs = [ReviewLog(card_id=r[0], rating=Rating(r[1]), review_datetime=datetime.fromtimestamp(r[2] / 1000, timezone.utc),
                      review_duration=r[3]) for r in c.execute("SELECT card_id, rating, ts, duration_ms FROM revlog ORDER BY ts")]
    if len(logs) < 100:
        raise HTTPException(400, f"Need at least 100 reviews to optimize (have {len(logs)})")
    try:
        params = Optimizer(logs).compute_optimal_parameters()
    except Exception as e:
        raise HTTPException(400, f"Optimizer failed (is torch installed?): {e}")
    db.save_settings({"parameters": list(params)})
    return get_settings()

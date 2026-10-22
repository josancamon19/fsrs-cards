"""FSRS scheduling on top of py-fsrs, plus the Anki-style daily queue."""
import json
import random
from datetime import datetime, timedelta, timezone

from fsrs import Card, Rating, Scheduler, State

from . import db

NEW, LEARNING, REVIEW, RELEARNING = 0, 1, 2, 3
STATE_NAMES = {NEW: "new", LEARNING: "learning", REVIEW: "review", RELEARNING: "relearning"}
RATING_NAMES = {1: "again", 2: "hard", 3: "good", 4: "easy"}

_sched_cache: tuple[str, Scheduler] | None = None


def scheduler(settings: dict | None = None) -> Scheduler:
    global _sched_cache
    s = settings or db.get_settings()
    key = json.dumps([s["parameters"], s["desired_retention"], s["learning_steps_min"],
                      s["relearning_steps_min"], s["maximum_interval"], s["enable_fuzzing"]])
    if _sched_cache and _sched_cache[0] == key:
        return _sched_cache[1]
    kw = dict(
        desired_retention=s["desired_retention"],
        learning_steps=tuple(timedelta(minutes=m) for m in s["learning_steps_min"]),
        relearning_steps=tuple(timedelta(minutes=m) for m in s["relearning_steps_min"]),
        maximum_interval=s["maximum_interval"],
        enable_fuzzing=s["enable_fuzzing"],
    )
    if s["parameters"]:
        kw["parameters"] = tuple(s["parameters"])
    sch = Scheduler(**kw)
    _sched_cache = (key, sch)
    return sch


def _dt(ts: int | None) -> datetime | None:
    return None if ts is None else datetime.fromtimestamp(ts, timezone.utc)


def row_to_card(row) -> Card:
    if row["state"] == NEW:
        return Card(card_id=row["id"])
    return Card(card_id=row["id"], state=State(row["state"]), step=row["step"],
                stability=row["stability"], difficulty=row["difficulty"],
                due=_dt(row["due"]), last_review=_dt(row["last_review"]))


def retrievability(sch: Scheduler, stability, last_review, now_ts) -> float | None:
    if stability is None or last_review is None:
        return None
    elapsed = max(0, (now_ts - last_review) // 86400)
    return (1 + sch._FACTOR * elapsed / stability) ** sch._DECAY


def apply_review(row, rating: int, now: datetime, sch: Scheduler | None = None):
    """Pure: returns (new card column dict, revlog field dict). Deterministic per (card, reps)
    so that interval previews match what actually gets scheduled."""
    sch = sch or scheduler()
    card = row_to_card(row)
    now_ts = int(now.timestamp())
    r_before = retrievability(sch, row["stability"], row["last_review"], now_ts) if row["state"] != NEW else None
    elapsed = (now_ts - row["last_review"]) / 86400 if row["last_review"] else None
    random.seed(row["id"] * 7919 + row["reps"])
    new_card, _ = sch.review_card(card, Rating(rating), review_datetime=now)
    due_ts = int(new_card.due.timestamp())
    cols = {
        "state": int(new_card.state),
        "step": new_card.step,
        "stability": new_card.stability,
        "difficulty": new_card.difficulty,
        "due": due_ts,
        "last_review": now_ts,
        "reps": row["reps"] + 1,
        "lapses": row["lapses"] + (1 if rating == 1 and row["state"] == REVIEW else 0),
    }
    log = {
        "rating": rating,
        "state_before": row["state"],
        "state_after": cols["state"],
        "stability_before": row["stability"],
        "difficulty_before": row["difficulty"],
        "stability": new_card.stability,
        "difficulty": new_card.difficulty,
        "retrievability": r_before,
        "elapsed_days": elapsed,
        "interval_secs": due_ts - now_ts,
    }
    return cols, log


def preview(row, now: datetime) -> dict:
    sch = scheduler()
    return {str(r): apply_review(row, r, now, sch)[0]["due"] - int(now.timestamp()) for r in (1, 2, 3, 4)}


# ---------------------------------------------------------------- day + queue

def day_start(now: datetime, rollover: int) -> datetime:
    local = now.astimezone()
    start = local.replace(hour=rollover, minute=0, second=0, microsecond=0)
    if local < start:
        start -= timedelta(days=1)
    return start


def deck_ids(deck: str | None) -> list[int]:
    c = db.conn()
    if not deck:
        return [r[0] for r in c.execute("SELECT id FROM decks")]
    return [r[0] for r in c.execute(
        "SELECT id FROM decks WHERE name = ? OR name LIKE ? ESCAPE '\\'",
        (deck, deck.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "::%"))]


def limit_scope(ids: list[int]) -> list[int]:
    """Daily limits belong to the top-level deck: studying a subdeck uses up its parent's budget (like Anki),
    so every deck in a tree shows the same remaining new/review allowance."""
    c = db.conn()
    roots = {r[0].split("::")[0] for r in c.execute(f"SELECT name FROM decks WHERE id IN {_in(ids)}")}
    out = set(ids)
    for r in roots:
        out.update(deck_ids(r))
    return list(out)


def _in(ids):
    return "(" + ",".join(str(int(i)) for i in ids) + ")" if ids else "(NULL)"


def counts(ids: list[int], now: datetime, s: dict) -> dict:
    c = db.conn()
    ds = day_start(now, s["day_rollover_hour"])
    de = ds + timedelta(days=1)
    now_ts, ds_ms = int(now.timestamp()), int(ds.timestamp() * 1000)
    ind = _in(ids)
    done = c.execute(f"""
        SELECT SUM(r.state_before = 0), SUM(r.state_before = 2), COUNT(*)
        FROM revlog r JOIN cards c ON c.id = r.card_id
        WHERE r.ts >= ? AND r.imported = 0 AND c.deck_id IN {_in(limit_scope(ids))}""", (ds_ms,)).fetchone()
    new_done, rev_done, total_done = (done[0] or 0), (done[1] or 0), done[2]
    q = c.execute(f"""
        SELECT SUM(state = 0), SUM(state IN (1,3) AND due <= ?), SUM(state = 2 AND due < ?),
               SUM(state IN (1,3) AND due <= ?)
        FROM cards WHERE suspended = 0 AND deck_id IN {ind}""",
                  (now_ts, int(de.timestamp()), now_ts + s["learn_ahead_min"] * 60)).fetchone()
    new_total, learn_now, rev_due, learn_ahead = (q[0] or 0), (q[1] or 0), (q[2] or 0), (q[3] or 0)
    return {
        "new": max(0, min(new_total, s["new_per_day"] - new_done)),
        "learning": learn_now,
        "learning_ahead": learn_ahead,
        "review": max(0, min(rev_due, s["reviews_per_day"] - rev_done)),
        "done_today": total_done,
        "day_end": int(de.timestamp()),
    }


def next_card(ids: list[int], now: datetime, s: dict, exclude: list[int] | None = None):
    """`exclude`: cards to hold back for now, oldest first (skipped cards, then the card just answered).
    When nothing else is left they come back, oldest first."""
    c = db.conn()
    ind = _in(ids)
    now_ts = int(now.timestamp())
    cnt = counts(ids, now, s)
    ex = f"AND id NOT IN ({','.join(str(int(x)) for x in exclude)})" if exclude else ""
    base = f"SELECT * FROM cards WHERE suspended = 0 AND deck_id IN {ind} {ex}"

    row = c.execute(f"{base} AND state IN (1,3) AND due <= ? ORDER BY due LIMIT 1", (now_ts,)).fetchone()
    if row:
        return row, cnt
    want_new = cnt["new"] > 0
    want_rev = cnt["review"] > 0
    if want_new and want_rev:
        # interleave: spread new cards evenly through the reviews
        ratio = max(1, cnt["review"] // cnt["new"])
        want_rev = cnt["done_today"] % (ratio + 1) != ratio
    if want_rev:
        row = c.execute(f"{base} AND state = 2 AND due < ? ORDER BY due, id LIMIT 1", (cnt["day_end"],)).fetchone()
        if row:
            return row, cnt
    if cnt["new"] > 0:
        row = c.execute(f"{base} AND state = 0 ORDER BY due, id LIMIT 1").fetchone()
        if row:
            return row, cnt
    if cnt["review"] > 0:
        row = c.execute(f"{base} AND state = 2 AND due < ? ORDER BY due, id LIMIT 1", (cnt["day_end"],)).fetchone()
        if row:
            return row, cnt
    row = c.execute(f"{base} AND state IN (1,3) AND due <= ? ORDER BY due LIMIT 1",
                    (now_ts + s["learn_ahead_min"] * 60,)).fetchone()
    if row:
        return row, cnt
    if exclude:  # only held-back cards are left: release the oldest one
        return next_card(ids, now, s, exclude[1:])
    return None, cnt


def next_learning_due(ids: list[int]) -> int | None:
    r = db.conn().execute(
        f"SELECT MIN(due) FROM cards WHERE suspended = 0 AND state IN (1,3) AND deck_id IN {_in(ids)}").fetchone()
    return r[0]


# ---------------------------------------------------------------- import replay

def replay(card_row: dict, entries: list[tuple[int, int, int]], sch: Scheduler):
    """Rebuild FSRS state from an Anki review history. entries: (ts_ms, ease, duration_ms).
    Returns (final card cols, revlog rows)."""
    row = dict(card_row)
    logs = []
    for ts, ease, dur in entries:
        if ease == 0:  # Anki "forget"/reset entry
            row.update(state=NEW, step=None, stability=None, difficulty=None, last_review=None, reps=0, lapses=0)
            continue
        now = datetime.fromtimestamp(ts / 1000, timezone.utc)
        cols, log = apply_review(row, ease, now, sch)
        log.update(card_id=row["id"], ts=ts, duration_ms=dur, imported=1)
        logs.append(log)
        row.update(cols)
    return row, logs

"""SQLite storage. One file, WAL mode, a single shared connection (single user)."""
import json
import os
import sqlite3
import threading
from pathlib import Path

DATA_DIR = Path(os.environ.get("ANKI_FSRS_DATA", Path(__file__).resolve().parent.parent / "data"))
MEDIA_DIR = DATA_DIR / "media"
DB_PATH = DATA_DIR / "anki.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS decks (
  id    INTEGER PRIMARY KEY,
  name  TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS notetypes (
  id        INTEGER PRIMARY KEY,
  name      TEXT NOT NULL,
  kind      INTEGER NOT NULL DEFAULT 0,      -- 0 standard, 1 cloze
  fields    TEXT NOT NULL,                   -- JSON list of field names
  templates TEXT NOT NULL,                   -- JSON list of {name,qfmt,afmt}
  css       TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS notes (
  id          INTEGER PRIMARY KEY,
  guid        TEXT,
  notetype_id INTEGER NOT NULL,
  fields      TEXT NOT NULL,                 -- JSON list of field values
  tags        TEXT NOT NULL DEFAULT '',
  source_url  TEXT,                          -- e.g. bear://x-callback-url/open-note?id=...&header=...
  source_label TEXT,
  edited_at   INTEGER                        -- set when edited in-app; re-imports then keep our fields
);
CREATE TABLE IF NOT EXISTS cards (
  id          INTEGER PRIMARY KEY,
  note_id     INTEGER NOT NULL,
  deck_id     INTEGER NOT NULL,
  ord         INTEGER NOT NULL,
  state       INTEGER NOT NULL DEFAULT 0,    -- 0 new, 1 learning, 2 review, 3 relearning
  step        INTEGER,
  stability   REAL,
  difficulty  REAL,
  due         INTEGER NOT NULL DEFAULT 0,    -- unix seconds (new: insertion position)
  last_review INTEGER,
  reps        INTEGER NOT NULL DEFAULT 0,
  lapses      INTEGER NOT NULL DEFAULT 0,
  suspended   INTEGER NOT NULL DEFAULT 0,
  suspended_at   INTEGER,                    -- unix s; when it was suspended (rewrite queue)
  suspend_reason TEXT
);
CREATE INDEX IF NOT EXISTS ix_cards_queue ON cards(deck_id, suspended, state, due);
CREATE INDEX IF NOT EXISTS ix_cards_note ON cards(note_id);
CREATE TABLE IF NOT EXISTS revlog (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  card_id           INTEGER NOT NULL,
  ts                INTEGER NOT NULL,        -- unix ms
  rating            INTEGER NOT NULL,        -- 1 again, 2 hard, 3 good, 4 easy
  state_before      INTEGER NOT NULL,
  state_after       INTEGER NOT NULL,
  stability_before  REAL,
  difficulty_before REAL,
  stability         REAL,
  difficulty        REAL,
  retrievability    REAL,                    -- predicted R at review time (null for new)
  elapsed_days      REAL,
  interval_secs     INTEGER,                 -- scheduled interval after this review
  duration_ms       INTEGER,
  imported          INTEGER NOT NULL DEFAULT 0,
  prev              TEXT                     -- JSON snapshot of card row before (for undo)
);
CREATE INDEX IF NOT EXISTS ix_revlog_card ON revlog(card_id, ts);
CREATE INDEX IF NOT EXISTS ix_revlog_ts ON revlog(ts);
CREATE TABLE IF NOT EXISTS responses (       -- spoken answers (text only; audio is deleted once transcribed)
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  card_id        INTEGER NOT NULL,
  note_id        INTEGER,
  ts             INTEGER NOT NULL,           -- unix ms when the card was shown
  duration_ms    INTEGER,
  reveal_ms      INTEGER,                    -- ms into the recording when the answer was revealed
  rating         INTEGER,
  flagged        INTEGER NOT NULL DEFAULT 0, -- "dive into this later"
  note           TEXT,                       -- your note on why it's flagged
  question       TEXT,                       -- plain-text snapshot of the card at the time
  answer         TEXT,
  status         TEXT NOT NULL,              -- pending, done, empty, error
  transcript     TEXT,                       -- cleaned up; the recall attempt, before the card was flipped
  transcript_raw TEXT,
  transcript_after     TEXT,                 -- cleaned up; what was said after the answer was revealed
  transcript_after_raw TEXT,
  analysis       TEXT,                       -- JSON {unsure: [...], missed: [...]}
  error          TEXT,
  model          TEXT,
  audio_path     TEXT,                       -- set only while waiting for transcription (before the flip)
  audio_after_path TEXT,                     -- same, for the part after the flip
  done_at        INTEGER
);
CREATE INDEX IF NOT EXISTS ix_responses_card ON responses(card_id, ts);
CREATE INDEX IF NOT EXISTS ix_responses_ts ON responses(ts);
CREATE TABLE IF NOT EXISTS chats (           -- voice conversations about a card (OpenAI Realtime), text only
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  card_id     INTEGER NOT NULL,
  note_id     INTEGER,
  response_id INTEGER,                       -- the spoken answer given right before the chat, if any
  started_at  INTEGER NOT NULL,              -- unix ms
  ended_at    INTEGER,
  question    TEXT,                          -- plain-text snapshot of the card
  answer      TEXT,
  turns       TEXT NOT NULL DEFAULT '[]',    -- JSON [{role: user|assistant, text, ts}]; the system prompt is not stored
  summary     TEXT,                          -- JSON {topics, takeaways, follow_ups}
  status      TEXT NOT NULL DEFAULT 'live',  -- live, ended, summarized
  model       TEXT
);
CREATE INDEX IF NOT EXISTS ix_chats_card ON chats(card_id, started_at);
CREATE TABLE IF NOT EXISTS settings (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
"""

DEFAULT_SETTINGS = {
    "desired_retention": 0.9,
    "parameters": None,              # None -> FSRS-6 defaults
    "learning_steps_min": [1, 10],
    "relearning_steps_min": [10],
    "maximum_interval": 36500,
    "enable_fuzzing": True,
    "new_per_day": 20,
    "reviews_per_day": 200,
    "day_rollover_hour": 4,
    "learn_ahead_min": 20,
}

_lock = threading.RLock()
_conn: sqlite3.Connection | None = None


def conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        MEDIA_DIR.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(DB_PATH, check_same_thread=False, isolation_level=None)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA synchronous=NORMAL")
        c.execute("PRAGMA foreign_keys=OFF")
        c.execute("PRAGMA cache_size=-64000")
        c.executescript(SCHEMA)
        cols = {r[1] for r in c.execute("PRAGMA table_info(notes)")}
        for col, typ in (("source_url", "TEXT"), ("source_label", "TEXT"), ("edited_at", "INTEGER")):  # migrate older DBs
            if col not in cols:
                c.execute(f"ALTER TABLE notes ADD COLUMN {col} {typ}")
        ccols = {r[1] for r in c.execute("PRAGMA table_info(cards)")}
        for col, typ in (("suspended_at", "INTEGER"), ("suspend_reason", "TEXT")):
            if col not in ccols:
                c.execute(f"ALTER TABLE cards ADD COLUMN {col} {typ}")
        rcols = {r[1] for r in c.execute("PRAGMA table_info(responses)")}
        for col in ("transcript_after", "transcript_after_raw", "audio_after_path"):
            if col not in rcols:
                c.execute(f"ALTER TABLE responses ADD COLUMN {col} TEXT")
        _conn = c
    return _conn


def lock():
    return _lock


def get_settings() -> dict:
    rows = conn().execute("SELECT key, value FROM settings").fetchall()
    s = dict(DEFAULT_SETTINGS)
    s.update({r["key"]: json.loads(r["value"]) for r in rows})
    return s


def save_settings(values: dict) -> None:
    c = conn()
    with _lock:
        c.execute("BEGIN")
        for k, v in values.items():
            if k in DEFAULT_SETTINGS:
                c.execute("INSERT OR REPLACE INTO settings(key, value) VALUES (?, ?)", (k, json.dumps(v)))
        c.execute("COMMIT")

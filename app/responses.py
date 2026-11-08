"""Spoken answers: audio recorded while a card is on screen is transcribed in the background, then deleted.

Only the text is kept. Pipeline per response:
  1. gpt-transcribe (OpenAI /v1/audio/transcriptions), with the card text as context for technical vocabulary
  2. a small model cleans the transcript like a dictation app would (fillers, false starts, punctuation)
     and lists what you were unsure about and what the reference answer has that you missed
"""
import json
import os
import queue
import re
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from . import db, prompts, render

API = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
TRANSCRIBE_MODEL = os.environ.get("TRANSCRIBE_MODEL", "gpt-transcribe")
CLEANUP_MODEL = os.environ.get("CLEANUP_MODEL", "gpt-6-luna")
AUDIO_DIR = db.DATA_DIR / "audio_pending"   # audio lives here only until it is transcribed
AUDIO_EXT = {"audio/webm": "webm", "audio/mp4": "m4a", "audio/ogg": "ogg", "audio/mpeg": "mp3", "audio/wav": "wav"}

_jobs: queue.Queue[int] = queue.Queue()
_worker: threading.Thread | None = None


def api_key() -> str:
    return os.environ.get("OPENAI_API_KEY", "")


def card_text(card_id: int) -> tuple[str, str]:
    """Plain-text question and back side, snapshotted with each response (cards may be rewritten later)."""
    row = db.conn().execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()
    r = render.render_card(row)
    # drop deck-template header chips (section / level / kind) so only the actual question and answer remain
    clean = lambda h: render.strip_html(re.sub(r'<div class="(?:hdr|meta)">.*?</div>', " ", h, flags=re.S))
    q, a = clean(r["question"]), clean(r["answer"])
    if a.startswith(q):
        a = a[len(q):].strip()
    return q, a


def _store(part: tuple[bytes, str] | None) -> str | None:
    if not part:
        return None
    data, mime = part
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    path = AUDIO_DIR / f"{uuid.uuid4().hex}.{AUDIO_EXT.get(mime.split(';')[0].strip(), 'webm')}"
    path.write_bytes(data)
    return path.name


def save_upload(card_id: int, before: tuple[bytes, str] | None, after: tuple[bytes, str] | None,
                background: bool = True, typed: str = "", **meta) -> int:
    """`before` is the recall attempt (until the card was flipped), `after` is what was said once the answer showed.
    `typed`: what was written in a pattern card's editor (kept in meta.typed, graded with the spoken part).
    background=False: the caller runs process() itself (pattern cards are graded while you wait)."""
    q, a = card_text(card_id)
    if typed.strip():
        try:
            m = json.loads(meta.get("meta") or "{}")
        except ValueError:
            m = {}
        meta["meta"] = json.dumps({**m, "typed": typed})
    c = db.conn()
    with db.lock():
        note = c.execute("SELECT note_id FROM cards WHERE id = ?", (card_id,)).fetchone()
        rid = c.execute("""INSERT INTO responses(card_id, note_id, ts, duration_ms, reveal_ms, rating, flagged,
                           question, answer, status, audio_path, audio_after_path, meta) VALUES (?,?,?,?,?,?,?,?,?, 'pending', ?, ?, ?)""",
                        (card_id, note["note_id"], meta["ts"], meta.get("duration_ms"), meta.get("reveal_ms"),
                         meta.get("rating"), int(bool(meta.get("flagged"))), q, a, _store(before), _store(after),
                         meta.get("meta"))).lastrowid
    if background:
        enqueue(rid)
    return rid


def enqueue(rid: int) -> None:
    global _worker
    _jobs.put(rid)
    if _worker is None or not _worker.is_alive():
        _worker = threading.Thread(target=_run, daemon=True, name="transcriber")
        _worker.start()


def fix_snapshots() -> None:
    """Older snapshots kept deck-template header labels ("L1 · Core", "RL for LLMs · Basic") glued to the question.
    Re-snapshot those from the card so lists show the question first."""
    c = db.conn()
    for table in ("responses", "chats"):
        rows = c.execute(f"SELECT id, card_id, question FROM {table} WHERE question GLOB '*L[0-9] · *'").fetchall()
        for r in rows:
            if not c.execute("SELECT 1 FROM cards WHERE id = ?", (r["card_id"],)).fetchone():
                continue
            q, a = card_text(r["card_id"])
            with db.lock():
                c.execute(f"UPDATE {table} SET question = ?, answer = ? WHERE id = ?", (q, a, r["id"]))


def resume_pending() -> None:
    """On startup, retry anything that was mid-flight when the machine stopped."""
    try:
        fix_snapshots()
    except Exception as e:
        print("snapshot fix skipped:", e)
    for (rid,) in db.conn().execute("SELECT id FROM responses WHERE status = 'pending'").fetchall():
        enqueue(rid)


def _run() -> None:
    while True:
        rid = _jobs.get()
        try:
            process(rid)
        except Exception as e:  # keep the audio so it can be retried
            _update(rid, status="error", error=str(e)[:500])


def _update(rid: int, **cols) -> None:
    with db.lock():
        db.conn().execute(f"UPDATE responses SET {', '.join(k + ' = ?' for k in cols)} WHERE id = ?", (*cols.values(), rid))


def process(rid: int) -> None:
    row = db.conn().execute("SELECT * FROM responses WHERE id = ?", (rid,)).fetchone()
    if not row or row["status"] == "done":
        return
    paths = [AUDIO_DIR / row[k] if row[k] else None for k in ("audio_path", "audio_after_path")]
    typed = _typed(row)
    if (not any(paths) and not typed) or any(p and not p.is_file() for p in paths):
        return _update(rid, status="error", error="audio file is gone (it is only kept until transcription)")
    if not api_key():
        return _update(rid, status="error", error="OPENAI_API_KEY is not set on the server")
    _update(rid, status="pending", error=None)
    before, after = (transcribe(p, row["question"], row["answer"]).strip() if p else "" for p in paths)
    pattern = pattern_fields(row["card_id"])
    if pattern is not None and (before or typed):  # pattern cards: grade the attempt (spoken and/or typed)
        try:
            out = grade_pattern(before, typed, pattern)
            text, analysis, model = out.pop("before").strip(), out, f"{TRANSCRIBE_MODEL} + {GRADE_MODEL}"
        except Exception as e:
            text, analysis, model = before, {"cleanup_error": str(e)[:300]}, TRANSCRIBE_MODEL
        _update(rid, status="done", transcript_raw=before, transcript=text, transcript_after_raw=after or None,
                transcript_after=after or None, analysis=json.dumps(analysis), audio_path=None, audio_after_path=None,
                model=model, error=None, done_at=int(time.time() * 1000))
    elif not before and not after:
        _update(rid, status="empty", transcript_raw="", transcript="", audio_path=None, audio_after_path=None,
                model=TRANSCRIBE_MODEL)
    else:
        try:
            out = cleanup(before, after, row["question"], row["answer"])
            text, text_after = out.pop("before").strip(), out.pop("after").strip()
            analysis, model = out, f"{TRANSCRIBE_MODEL} + {CLEANUP_MODEL}"
        except Exception as e:  # the raw transcripts are still worth keeping
            text, text_after, analysis, model = before, after, {"cleanup_error": str(e)[:300]}, TRANSCRIBE_MODEL
        _update(rid, status="done", transcript_raw=before, transcript=text, transcript_after_raw=after,
                transcript_after=text_after, analysis=json.dumps(analysis), audio_path=None, audio_after_path=None,
                model=model, error=None, done_at=int(time.time() * 1000))
    for p in paths:
        if p:
            p.unlink(missing_ok=True)


def _post(url: str, body: bytes, content_type: str, timeout: int = 180) -> dict:
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Authorization": f"Bearer {api_key()}", "Content-Type": content_type})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")
        try:
            detail = json.loads(detail)["error"]["message"]
        except Exception:
            pass
        raise RuntimeError(f"OpenAI {e.code}: {detail}") from None


_STOP = {"what", "which", "when", "where", "does", "this", "that", "with", "from", "into", "than", "then", "your", "about",
         "because", "between", "always", "never", "their", "there", "these", "those", "would", "could", "should"}


def keywords(question: str, answer: str) -> list[str]:
    """Technical terms from the card (PPO, Q(s,a), Monte, Jacobian, …) for the transcriber's `keywords`.
    A prose prompt is avoided on purpose: when the audio is faint the model can echo a prompt back as if it were speech."""
    text = re.sub(r"\\[()\[\]]", " ", f"{question} {answer}")
    out = []
    for w in re.findall(r"[A-Za-z][A-Za-z0-9'\-]*(?:\([^()\s]{1,8}\))?", text):
        technical = any(ch.isupper() for ch in w[1:]) or any(ch.isdigit() for ch in w) or "(" in w or len(w) >= 9 \
            or (w[0].isupper() and len(w) >= 4)
        if technical and w.lower() not in _STOP and w not in out and len(w) <= 40:
            out.append(w)
    return out[:25]


def transcribe(path: Path, question: str, answer: str) -> str:
    fields = [("model", TRANSCRIBE_MODEL), ("languages[]", "en"), ("response_format", "json")]
    fields += [("keywords[]", k) for k in keywords(question, answer)]
    boundary = uuid.uuid4().hex
    parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode() for k, v in fields]
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
                 f"Content-Type: application/octet-stream\r\n\r\n".encode() + path.read_bytes() + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return _post(f"{API}/audio/transcriptions", b"".join(parts), f"multipart/form-data; boundary={boundary}")["text"]


CLEANUP_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["before", "after", "unsure", "missed"],
    "properties": {"before": {"type": "string"}, "after": {"type": "string"},
                   "unsure": {"type": "array", "items": {"type": "string"}},
                   "missed": {"type": "array", "items": {"type": "string"}}},
}


def cleanup(before: str, after: str, question: str, answer: str) -> dict:
    body = {
        "model": CLEANUP_MODEL,
        "instructions": prompts.load("answer-cleanup"),
        "input": f"<card_question>\n{question}\n</card_question>\n<reference_answer>\n{answer}\n</reference_answer>\n"
                 f"<before_reveal>\n{before}\n</before_reveal>\n[card flipped: reference answer revealed]\n"
                 f"<after_reveal>\n{after}\n</after_reveal>",
        "reasoning": {"effort": "low"},
        "text": {"format": {"type": "json_schema", "name": "cleaned_answer", "strict": True, "schema": CLEANUP_SCHEMA}},
    }
    res = _post(f"{API}/responses", json.dumps(body).encode(), "application/json", timeout=120)
    text = "".join(c.get("text", "") for item in res.get("output", []) if item.get("type") == "message"
                   for c in item.get("content", []) if c.get("type") == "output_text")
    return json.loads(text)


# ---------------------------------------------------------------- pattern cards (LeetCode · Pattern)

PATTERN_NOTETYPE = "LeetCode · Pattern"
GRADE_MODEL = os.environ.get("GRADE_MODEL", CLEANUP_MODEL)
GRADE_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["before", "named_pattern", "verdict", "signal", "score", "got", "missed", "unsure", "feedback"],
    "properties": {
        "before": {"type": "string"},
        "named_pattern": {"type": "string"},
        "verdict": {"type": "string", "enum": ["correct", "acceptable", "wrong", "none"]},
        "signal": {"type": "string", "enum": ["named", "partial", "missing"]},
        "score": {"type": "integer", "enum": [1, 2, 3, 4]},
        "got": {"type": "array", "items": {"type": "string"}},
        "missed": {"type": "array", "items": {"type": "string"}},
        "unsure": {"type": "array", "items": {"type": "string"}},
        "feedback": {"type": "string"},
    },
}


def _typed(row) -> str:
    try:
        return (json.loads(row["meta"] or "{}").get("typed") or "").strip()
    except ValueError:
        return ""


def pattern_fields(card_id: int) -> dict | None:
    """The note's fields when the card is a pattern card, else None."""
    r = db.conn().execute("""SELECT n.fields, t.fields AS names, t.name FROM cards c JOIN notes n ON n.id = c.note_id
                             JOIN notetypes t ON t.id = n.notetype_id WHERE c.id = ?""", (card_id,)).fetchone()
    if not r or r["name"] != PATTERN_NOTETYPE:
        return None
    return dict(zip(json.loads(r["names"]), json.loads(r["fields"])))


def grade_pattern(spoken: str, typed: str, f: dict) -> dict:
    t = lambda k: render.strip_html(f.get(k, ""))
    body = {
        "model": GRADE_MODEL,
        "instructions": prompts.load("pattern-grade", cheatsheet=prompts.load("pattern-cheatsheet")),
        "input": f"<problem>\n{f.get('Number', '')}. {t('Title')} ({t('Difficulty')})\n{t('Statement')}\n</problem>\n"
                 f"<reference>\npattern: {t('Pattern')}\nvariant: {t('Variant')}\nalso acceptable: {t('Alternatives') or 'none'}\n"
                 f"signal: {t('Signal')}\napproach: {t('Approach')}\ncomplexity: {t('Complexity')}\n</reference>\n"
                 f"<spoken_attempt>\n{spoken}\n</spoken_attempt>\n<typed_attempt>\n{typed}\n</typed_attempt>",
        "reasoning": {"effort": "low"},
        "text": {"format": {"type": "json_schema", "name": "pattern_grade", "strict": True, "schema": GRADE_SCHEMA}},
    }
    res = _post(f"{API}/responses", json.dumps(body).encode(), "application/json", timeout=120)
    text = "".join(c.get("text", "") for item in res.get("output", []) if item.get("type") == "message"
                   for c in item.get("content", []) if c.get("type") == "output_text")
    return json.loads(text)


def to_dict(r) -> dict:
    d = {k: r[k] for k in ("id", "card_id", "note_id", "ts", "duration_ms", "reveal_ms", "rating", "question", "answer",
                           "status", "transcript", "transcript_raw", "transcript_after", "transcript_after_raw", "error", "model", "done_at", "note")}
    d["flagged"] = bool(r["flagged"])
    d["analysis"] = json.loads(r["analysis"]) if r["analysis"] else None
    d["meta"] = json.loads(r["meta"]) if r["meta"] else None
    d["typed"] = (d["meta"] or {}).get("typed") if isinstance(d["meta"], dict) else None
    return d

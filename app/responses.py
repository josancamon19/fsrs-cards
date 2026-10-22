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

from . import db, render

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
    clean = lambda h: render.strip_html(re.sub(r'<div class="hdr">.*?</div>', " ", h, flags=re.S))
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


def save_upload(card_id: int, before: tuple[bytes, str] | None, after: tuple[bytes, str] | None, **meta) -> int:
    """`before` is the recall attempt (until the card was flipped), `after` is what was said once the answer showed."""
    q, a = card_text(card_id)
    c = db.conn()
    with db.lock():
        note = c.execute("SELECT note_id FROM cards WHERE id = ?", (card_id,)).fetchone()
        rid = c.execute("""INSERT INTO responses(card_id, note_id, ts, duration_ms, reveal_ms, rating, flagged,
                           question, answer, status, audio_path, audio_after_path) VALUES (?,?,?,?,?,?,?,?,?, 'pending', ?, ?)""",
                        (card_id, note["note_id"], meta["ts"], meta.get("duration_ms"), meta.get("reveal_ms"),
                         meta.get("rating"), int(bool(meta.get("flagged"))), q, a, _store(before), _store(after))).lastrowid
    enqueue(rid)
    return rid


def enqueue(rid: int) -> None:
    global _worker
    _jobs.put(rid)
    if _worker is None or not _worker.is_alive():
        _worker = threading.Thread(target=_run, daemon=True, name="transcriber")
        _worker.start()


def resume_pending() -> None:
    """On startup, retry anything that was mid-flight when the machine stopped."""
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
    if not any(paths) or any(p and not p.is_file() for p in paths):
        return _update(rid, status="error", error="audio file is gone (it is only kept until transcription)")
    if not api_key():
        return _update(rid, status="error", error="OPENAI_API_KEY is not set on the server")
    _update(rid, status="pending", error=None)
    before, after = (transcribe(p, row["question"], row["answer"]).strip() if p else "" for p in paths)
    if not before and not after:
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


def transcribe(path: Path, question: str, answer: str) -> str:
    # The card text primes the model on the vocabulary (KL divergence, PPO, eigenvalues, …)
    prompt = (f"Someone is answering a flashcard out loud, in English. Question: {question[:400]} "
              f"Topic vocabulary: {answer[:600]}")
    fields = {"model": TRANSCRIBE_MODEL, "prompt": prompt, "languages[]": "en", "response_format": "json"}
    boundary = uuid.uuid4().hex
    parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode() for k, v in fields.items()]
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
                 f"Content-Type: application/octet-stream\r\n\r\n".encode() + path.read_bytes() + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return _post(f"{API}/audio/transcriptions", b"".join(parts), f"multipart/form-data; boundary={boundary}")["text"]


CLEANUP_INSTRUCTIONS = """You clean up a dictated answer to a flashcard, the way a high-quality dictation app (e.g. Wispr Flow) would.

The recording is split at the moment the speaker FLIPPED THE CARD to reveal the reference answer:
- <before_reveal>: their own recall attempt, made without seeing the answer.
- <after_reveal>: what they said once the answer was on screen (reading it, comparing, reacting, noting gaps).
Either part may be empty.

before / after: each part cleaned separately. Remove filler words (um, uh, like, you know), stutters, false starts and
self-corrections (keep only the corrected version), fix punctuation, casing and obvious mis-transcriptions of technical
terms using the card as context. Keep the speaker's own words, order, reasoning and mistakes: do NOT add facts, fix
wrong claims, or make it sound better than it was. Use math notation only if the speaker clearly dictated a formula.
Never move text between the two parts.

unsure: things the speaker said they don't remember, are unsure about, or want to look into later (from either part).
Each item must name the topic itself (e.g. "exact form of the softmax gradient / Jacobian"), never just
"I don't remember". Short phrases. Empty if none.

missed: key points of the reference answer that the BEFORE part left out or got wrong (short phrases). Only the
before part counts as recall: something said only after the reveal is still missed. Empty if the before part was
complete, or if it is empty (no attempt was made out loud)."""

CLEANUP_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["before", "after", "unsure", "missed"],
    "properties": {"before": {"type": "string"}, "after": {"type": "string"},
                   "unsure": {"type": "array", "items": {"type": "string"}},
                   "missed": {"type": "array", "items": {"type": "string"}}},
}


def cleanup(before: str, after: str, question: str, answer: str) -> dict:
    body = {
        "model": CLEANUP_MODEL,
        "instructions": CLEANUP_INSTRUCTIONS,
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


def to_dict(r) -> dict:
    d = {k: r[k] for k in ("id", "card_id", "note_id", "ts", "duration_ms", "reveal_ms", "rating", "question", "answer",
                           "status", "transcript", "transcript_raw", "transcript_after", "transcript_after_raw", "error", "model", "done_at", "note")}
    d["flagged"] = bool(r["flagged"])
    d["analysis"] = json.loads(r["analysis"]) if r["analysis"] else None
    return d

"""Voice conversations about a card (OpenAI Realtime over WebRTC).

The server builds the tutor's instructions from everything known about the card (text, FSRS state, review history,
earlier spoken answers and earlier conversations) and mints a short-lived client secret; the browser then talks to
OpenAI directly. Only the conversation text is stored: turns are appended as they are transcribed, and when the chat
ends a small model digests it into topics / takeaways / follow-ups.
"""
import json
import os
import time
from datetime import datetime

from . import db, responses, sched

RATING = {1: "Again", 2: "Hard", 3: "Good", 4: "Easy"}


def _day(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M")


def card_context(card_id: int, response_id: int | None = None) -> str:
    """Everything the tutor should know about this card, as plain text."""
    c = db.conn()
    row = c.execute("SELECT c.*, d.name AS deck FROM cards c LEFT JOIN decks d ON d.id = c.deck_id WHERE c.id = ?",
                    (card_id,)).fetchone()
    q, a = responses.card_text(card_id)
    now = int(time.time())
    r = sched.retrievability(sched.scheduler(), row["stability"], row["last_review"], now)
    out = [f"Deck: {row['deck']}", f"Card question: {q}", f"Card answer (reference): {a}",
           f"Memory state: {sched.STATE_NAMES[row['state']]}, {row['reps']} reviews, {row['lapses']} lapses"
           + (f", stability {row['stability']:.1f} days, difficulty {row['difficulty']:.1f}/10" if row["stability"] else "")
           + (f", predicted recall right now {r:.0%}" if r is not None else "")]
    revs = c.execute("SELECT ts, rating FROM revlog WHERE card_id = ? ORDER BY ts", (card_id,)).fetchall()
    if revs:
        out.append("Review history: " + "; ".join(f"{_day(x['ts'])} {RATING[x['rating']]}" for x in revs[-12:]))
    answers = c.execute("SELECT * FROM responses WHERE card_id = ? AND status = 'done' ORDER BY ts DESC LIMIT 6",
                        (card_id,)).fetchall()
    for i, x in enumerate(answers):
        label = "Joan's answer just now" if x["id"] == response_id else f"Earlier spoken answer ({_day(x['ts'])})"
        an = json.loads(x["analysis"]) if x["analysis"] else {}
        part = [f"{label}{', rated ' + RATING[x['rating']] if x['rating'] else ''}:",
                f"  before seeing the answer: {x['transcript'] or '(nothing said)'}"]
        if x["transcript_after"]:
            part.append(f"  after seeing the answer: {x['transcript_after']}")
        if an.get("unsure"):
            part.append("  unsure about: " + "; ".join(an["unsure"]))
        if an.get("missed"):
            part.append("  missed: " + "; ".join(an["missed"]))
        out.append("\n".join(part))
    chats = c.execute("SELECT started_at, summary FROM chats WHERE card_id = ? AND summary IS NOT NULL "
                      "ORDER BY started_at DESC LIMIT 5", (card_id,)).fetchall()
    for ch in chats:
        s = json.loads(ch["summary"])
        out.append(f"Earlier conversation about this card ({_day(ch['started_at'])}): topics {', '.join(s.get('topics', []))}; "
                   f"takeaways: {'; '.join(s.get('takeaways', []))}"
                   + (f"; still open: {'; '.join(s['follow_ups'])}" if s.get("follow_ups") else ""))
    return "\n\n".join(out)


def instructions(card_id: int, response_id: int | None = None) -> str:
    return f"""You are a helpful teacher for Joan, who is preparing for ML / AI research interviews with spaced-repetition flashcards.
Joan was just studying the card below and wants to talk about a few things related to it.

Rules:
- Do not speak first. Wait for Joan to talk.
- Answer briefly and concisely: one to three sentences unless Joan asks you to go deeper. Spoken style, no lists read aloud.
- Use the context: the card, its review history, Joan's earlier answers (what was missed or uncertain), and earlier conversations.
  Point out a gap from an earlier answer only when it is relevant to what Joan asks.
- Be precise about math and ML; say so when something is uncertain instead of guessing.
- If Joan's answer for this attempt arrives mid-conversation as a system message, take it into account.

Context about the card:
{card_context(card_id, response_id)}"""


REALTIME_MODEL = os.environ.get("REALTIME_MODEL", "gpt-realtime-2.1")
REALTIME_VOICE = os.environ.get("REALTIME_VOICE", "marin")


def client_secret(card_id: int, response_id: int | None) -> dict:
    """Mint a short-lived key for the browser. The whole session config (instructions included) lives in the key,
    so the browser never sees the server's API key and can't change the prompt."""
    session = {
        "type": "realtime", "model": REALTIME_MODEL, "instructions": instructions(card_id, response_id),
        "audio": {
            "input": {"transcription": {"model": responses.TRANSCRIBE_MODEL},
                      "noise_reduction": {"type": "near_field"},
                      # answers only after Joan speaks; never opens on its own (no idle timeout)
                      "turn_detection": {"type": "semantic_vad", "eagerness": "auto", "create_response": True,
                                         "interrupt_response": True}},
            "output": {"voice": REALTIME_VOICE},
        },
    }
    body = {"expires_after": {"anchor": "created_at", "seconds": 600}, "session": session}
    return responses._post(f"{responses.API}/realtime/client_secrets", json.dumps(body).encode(), "application/json", timeout=30)


def create(card_id: int, response_id: int | None, model: str) -> int:
    c = db.conn()
    q, a = responses.card_text(card_id)
    with db.lock():
        note = c.execute("SELECT note_id FROM cards WHERE id = ?", (card_id,)).fetchone()
        return c.execute("INSERT INTO chats(card_id, note_id, response_id, started_at, question, answer, model) "
                         "VALUES (?,?,?,?,?,?,?)", (card_id, note["note_id"], response_id, int(time.time() * 1000), q, a,
                                                    model)).lastrowid


def add_turns(chat_id: int, turns: list[dict]) -> int:
    """Append transcribed turns. Each turn carries the Realtime item id, so a resent turn isn't stored twice."""
    c = db.conn()
    with db.lock():
        row = c.execute("SELECT turns FROM chats WHERE id = ?", (chat_id,)).fetchone()
        if not row:
            raise KeyError(chat_id)
        have = json.loads(row["turns"])
        seen = {t.get("id") for t in have if t.get("id")}
        for t in turns:
            text = (t.get("text") or "").strip()
            if text and t.get("role") in ("user", "assistant") and (not t.get("id") or t["id"] not in seen):
                have.append({"id": t.get("id"), "role": t["role"], "text": text, "ts": int(t.get("ts") or time.time() * 1000)})
        have.sort(key=lambda t: t["ts"])
        c.execute("UPDATE chats SET turns = ? WHERE id = ?", (json.dumps(have), chat_id))
        return len(have)


SUMMARY_INSTRUCTIONS = """You digest a short spoken conversation between Joan (a learner) and a tutor about one flashcard.
Return:
- topics: the specific things Joan asked about (short noun phrases)
- takeaways: what Joan should remember from the conversation, as precise one-line facts or explanations
- follow_ups: questions left open, or things Joan said they want to look into later
Only use what was actually said. Empty lists are fine."""

SUMMARY_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["topics", "takeaways", "follow_ups"],
    "properties": {k: {"type": "array", "items": {"type": "string"}} for k in ("topics", "takeaways", "follow_ups")},
}


def end(chat_id: int) -> None:
    """Mark the chat ended and digest it (runs in the background worker thread)."""
    with db.lock():
        db.conn().execute("UPDATE chats SET ended_at = COALESCE(ended_at, ?), status = 'ended' WHERE id = ?",
                          (int(time.time() * 1000), chat_id))
    row = db.conn().execute("SELECT * FROM chats WHERE id = ?", (chat_id,)).fetchone()
    turns = json.loads(row["turns"])
    if not turns or not responses.api_key():
        return
    convo = "\n".join(f"{'Joan' if t['role'] == 'user' else 'Tutor'}: {t['text']}" for t in turns)
    body = {"model": responses.CLEANUP_MODEL, "instructions": SUMMARY_INSTRUCTIONS, "reasoning": {"effort": "low"},
            "input": f"<card_question>\n{row['question']}\n</card_question>\n<card_answer>\n{row['answer']}\n</card_answer>\n"
                     f"<conversation>\n{convo}\n</conversation>",
            "text": {"format": {"type": "json_schema", "name": "chat_digest", "strict": True, "schema": SUMMARY_SCHEMA}}}
    res = responses._post(f"{responses.API}/responses", json.dumps(body).encode(), "application/json", timeout=120)
    text = "".join(c.get("text", "") for item in res.get("output", []) if item.get("type") == "message"
                   for c in item.get("content", []) if c.get("type") == "output_text")
    summary = json.loads(text)
    with db.lock():
        db.conn().execute("UPDATE chats SET summary = ?, status = 'summarized' WHERE id = ?", (json.dumps(summary), chat_id))


def to_dict(r) -> dict:
    return {"id": r["id"], "card_id": r["card_id"], "note_id": r["note_id"], "response_id": r["response_id"],
            "started_at": r["started_at"], "ended_at": r["ended_at"], "question": r["question"], "status": r["status"],
            "model": r["model"], "turns": json.loads(r["turns"]),
            "summary": json.loads(r["summary"]) if r["summary"] else None}


def end_safely(chat_id: int) -> None:
    try:
        end(chat_id)
    except Exception as e:  # keep the turns; the digest can be retried on the next start
        print(f"chat {chat_id}: digest failed: {e}")


def resume() -> None:
    """On startup: chats left open (tab closed mid-conversation) or never digested get ended and digested now."""
    stale = int(time.time() * 1000) - 2 * 3600 * 1000
    for (cid,) in db.conn().execute("SELECT id FROM chats WHERE turns != '[]' AND summary IS NULL AND "
                                    "(status = 'ended' OR started_at < ?)", (stale,)).fetchall():
        end_safely(cid)

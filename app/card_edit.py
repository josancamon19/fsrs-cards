"""AI edits of one card, asked for from the card editor.

The model gets the card (fields, rendered text, images), its FSRS history, Joan's spoken answers and conversations
about it, the earlier edit requests on the note, and the card principles with examples of cards Joan discarded and
cards that work (prompts/card-edit.md). It thinks at max effort, so a request runs in the background and can take
minutes; its proposal is stored and only reaches the note when Joan saves it in the editor. Every saved version is
recorded too, so card_edits holds the note's full edit history.
"""
import base64
import json
import os
import re
import threading
import time

from . import chat, db, prompts, render, responses

MODEL = os.environ.get("CARD_EDIT_MODEL", "gpt-6.1-sol")
EFFORT = os.environ.get("CARD_EDIT_EFFORT", "max")
_MIME = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif", "webp": "image/webp"}


def note_fields(note_id: int) -> dict:
    n = db.conn().execute("""SELECT n.fields, t.fields AS names FROM notes n JOIN notetypes t ON t.id = n.notetype_id
                             WHERE n.id = ?""", (note_id,)).fetchone()
    names, vals = json.loads(n["names"]), json.loads(n["fields"])
    return dict(zip(names, vals + [""] * (len(names) - len(vals))))


def _short(s: str, n: int = 700) -> str:
    return s if len(s) <= n else s[:n] + " …"


def examples(exclude_note: int) -> str:
    """Cards Joan suspended as badly written (with the reason), and cards rewritten or written since (they follow the
    principles). Both come from the live database, so the examples grow with the decks."""
    c = db.conn()
    bad = c.execute("""SELECT c.id, c.suspend_reason FROM cards c WHERE c.suspended = 1 AND c.note_id != ?
                       AND c.suspend_reason IS NOT NULL AND c.suspend_reason != '' AND c.suspend_reason NOT LIKE 'Replaced by%'
                       AND c.suspend_reason NOT LIKE 'Cloze c% removed in an edit'
                       ORDER BY c.suspended_at DESC LIMIT 6""", (exclude_note,)).fetchall()
    good = c.execute("""SELECT n.id FROM notes n WHERE n.edited_at IS NOT NULL AND n.id != ?
                        AND NOT EXISTS (SELECT 1 FROM cards c WHERE c.note_id = n.id AND c.suspended = 1)
                        ORDER BY n.edited_at DESC LIMIT 6""", (exclude_note,)).fetchall()
    out = ["## Discarded (Joan suspended these as badly written)"]
    for r in bad:
        q, a = responses.card_text(r["id"])
        out.append(f"Front: {_short(q, 300)}\nBack: {_short(a, 300)}\nWhy discarded: {r['suspend_reason']}")
    out.append("## Good (written or rewritten to the principles)")
    for r in good:
        out.append(json.dumps({k: _short(v) for k, v in note_fields(r["id"]).items() if v}, ensure_ascii=False))
    return "\n\n".join(out)


def history_text(note_id: int, card_id: int) -> str:
    c = db.conn()
    parts = []
    chats = c.execute("""SELECT * FROM chats WHERE note_id = ? AND turns != '[]' ORDER BY started_at DESC LIMIT 4""",
                      (note_id,)).fetchall()
    for x in reversed(chats):
        s = json.loads(x["summary"]) if x["summary"] else {}
        turns = json.loads(x["turns"])
        convo = "\n".join(f"  {'Joan' if t['role'] == 'user' else 'Tutor'}: {'[wrote] ' if t.get('kind') == 'math' else ''}"
                          f"{_short(t['text'], 400)}" for t in turns[-16:])
        parts.append(f"Conversation {chat._day(x['started_at'])}"
                     + (f" (takeaways: {'; '.join(s.get('takeaways', []))})" if s.get("takeaways") else "") + f":\n{convo}")
    edits = c.execute("""SELECT * FROM card_edits WHERE note_id = ? AND status = 'done' ORDER BY ts DESC LIMIT 10""",
                      (note_id,)).fetchall()
    if edits:
        lines = []
        for e in reversed(edits):
            when = chat._day(e["ts"])
            lines.append(f"- {when} request: {e['instruction']!r} → {e['explanation']}" if e["kind"] == "ai"
                         else f"- {when} Joan saved the card" + (" and reset its memory" if e["reset_memory"] else ""))
        parts.append("Earlier edits on this card, oldest first:\n" + "\n".join(lines))
    return "\n\n".join(parts)


def _images(fields: dict) -> list[dict]:
    out = []
    for src in dict.fromkeys(re.findall(r'<img[^>]+src="([^"]+)"', " ".join(fields.values()))):
        p = db.MEDIA_DIR / os.path.basename(src)
        mime = _MIME.get(p.suffix.lower().lstrip("."))
        if mime and p.is_file() and p.stat().st_size < 4_000_000 and len(out) < 4:
            out.append({"type": "input_image", "image_url": f"data:{mime};base64,{base64.b64encode(p.read_bytes()).decode()}"})
    return out


def schema(names: list[str]) -> dict:
    return {"type": "object", "additionalProperties": False, "required": ["fields", "explanation", "reset_memory"],
            "properties": {
                "fields": {"type": "object", "additionalProperties": False, "required": names,
                           "properties": {k: {"type": "string"} for k in names}},
                "explanation": {"type": "string"}, "reset_memory": {"type": "boolean"}}}


def start(card_id: int, instruction: str, fields: dict) -> int:
    """Queue a request. `fields` are the editor's current values (they may hold unsaved changes or an earlier proposal)."""
    c = db.conn()
    note_id = c.execute("SELECT note_id FROM cards WHERE id = ?", (card_id,)).fetchone()["note_id"]
    current = {**note_fields(note_id), **{k: v for k, v in fields.items() if k in note_fields(note_id)}}
    with db.lock():
        eid = c.execute("""INSERT INTO card_edits(note_id, card_id, ts, kind, instruction, fields_before, status, model)
                           VALUES (?,?,?,?,?,?,?,?)""", (note_id, card_id, int(time.time() * 1000), "ai", instruction.strip(),
                                                         json.dumps(current), "pending", f"{MODEL} ({EFFORT})")).lastrowid
    threading.Thread(target=run, args=(eid,), daemon=True).start()
    return eid


def run(eid: int) -> None:
    e = db.conn().execute("SELECT * FROM card_edits WHERE id = ?", (eid,)).fetchone()
    try:
        fields = json.loads(e["fields_before"])
        card = db.conn().execute("SELECT * FROM cards WHERE id = ?", (e["card_id"],)).fetchone()
        shown = render.render_card(card, fields)
        context = "\n\n".join(x for x in (chat.card_context(e["card_id"]), history_text(e["note_id"], e["card_id"])) if x)
        text = (f"<card_context>\n{context}\n</card_context>\n\n"
                f"<current_fields notetype=\"{shown['notetype']}\">\n{json.dumps(fields, ensure_ascii=False, indent=1)}\n</current_fields>\n\n"
                f"<rendered>\nFront: {render.strip_html(shown['question'])}\nBack: {render.strip_html(shown['answer'])}\n</rendered>\n\n"
                f"<request>\n{e['instruction']}\n</request>")
        body = {"model": MODEL, "reasoning": {"effort": EFFORT},
                "instructions": prompts.load("card-edit", principles=prompts.load("card-principles"),
                                             examples=examples(e["note_id"])),
                "input": [{"role": "user", "content": [{"type": "input_text", "text": text}, *_images(fields)]}],
                "text": {"format": {"type": "json_schema", "name": "card_edit", "strict": True, "schema": schema(list(fields))}}}
        res = responses._post(f"{responses.API}/responses", json.dumps(body).encode(), "application/json", timeout=1800)
        out = json.loads("".join(c.get("text", "") for item in res.get("output", []) if item.get("type") == "message"
                                 for c in item.get("content", []) if c.get("type") == "output_text"))
        with db.lock():
            db.conn().execute("""UPDATE card_edits SET fields_after = ?, explanation = ?, reset_memory = ?, status = 'done',
                                 done_at = ? WHERE id = ?""", (json.dumps(out["fields"]), out["explanation"],
                                                              int(out["reset_memory"]), int(time.time() * 1000), eid))
    except Exception as ex:
        with db.lock():
            db.conn().execute("UPDATE card_edits SET status = 'error', error = ?, done_at = ? WHERE id = ?",
                              (str(ex)[:500], int(time.time() * 1000), eid))


def record_saved(note_id: int, before: dict, after: dict, reset: bool) -> None:
    with db.lock():
        db.conn().execute("""INSERT INTO card_edits(note_id, ts, kind, fields_before, fields_after, reset_memory, status)
                             VALUES (?,?,?,?,?,?,?)""", (note_id, int(time.time() * 1000), "saved", json.dumps(before),
                                                         json.dumps(after), int(reset), "done"))


def fail_stale() -> None:
    """On startup: requests that were running when the server stopped will never finish."""
    with db.lock():
        db.conn().execute("UPDATE card_edits SET status = 'error', error = 'the server restarted while this was running' "
                          "WHERE status = 'pending'")


def to_dict(r) -> dict:
    return {k: r[k] for k in ("id", "note_id", "card_id", "ts", "kind", "instruction", "explanation", "status", "error",
                              "model", "done_at")} | {
        "reset_memory": bool(r["reset_memory"]),
        "fields_before": json.loads(r["fields_before"]) if r["fields_before"] else None,
        "fields_after": json.loads(r["fields_after"]) if r["fields_after"] else None}

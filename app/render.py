"""Anki template rendering: fields, conditionals, filters, cloze, type-in, sounds, media paths."""
import html
import json
import re
from functools import lru_cache

from . import db

_SECTION = re.compile(r"\{\{([#^])\s*([^}]+?)\s*\}\}(.*?)\{\{/\s*\2\s*\}\}", re.S)
_TAG = re.compile(r"\{\{(?!FrontSide\}\})([^#^/{}][^{}]*?)\}\}")
_CLOZE = re.compile(r"\{\{c(\d+)::(.*?)(?:::(.*?))?\}\}", re.S)
CLOZE_TEXT = re.compile(r"\{\{c\d+::(.*?)(?:::[^}]*)?\}\}", re.S)
_SOUND = re.compile(r"\[sound:([^\]]+)\]")
_SRC = re.compile(r"""(\bsrc\s*=\s*)(["']?)(?!https?:|data:|/|#)([^"'\s>]+)\2""", re.I)
_HTML = re.compile(r"<[^>]+>")
_FURI = re.compile(r" ?([^ >\[]+?)\[(.+?)\]")


def strip_html(s: str) -> str:
    s = re.sub(r"<li[^>]*>", " • ", s)
    s = re.sub(r"<br\s*/?>|</?(div|p|ol|ul|tr|h\d)[^>]*>", " ", s)
    return re.sub(r"\s+", " ", html.unescape(_HTML.sub("", s))).strip()


def _cloze(text: str, n: int, answer: bool, only_active: bool = False) -> str:
    def rep(m):
        num, body, hint = int(m.group(1)), m.group(2), m.group(3)
        if num != n:
            return "" if only_active else body
        if answer:
            return f'<span class="cloze">{body}</span>'
        return f'<span class="cloze">[{html.escape(hint) if hint else "..."}]</span>'
    if only_active:
        return ", ".join(m.group(2) for m in _CLOZE.finditer(text) if int(m.group(1)) == n)
    prev = None
    while prev != text:  # resolve nested clozes inside-out
        prev, text = text, _CLOZE.sub(rep, text)
    return text


def _furigana(s, mode):
    if mode == "kanji":
        return _FURI.sub(r"\1", s)
    if mode == "kana":
        return _FURI.sub(r"\2", s)
    return _FURI.sub(r"<ruby><rb>\1</rb><rt>\2</rt></ruby>", s)


def _apply(tag: str, ctx: dict, answer: bool, card_ord: int, type_state: dict) -> str:
    parts = [p.strip() for p in tag.split(":")]
    name, filters = parts[-1], parts[:-1]
    if name == "Tags":
        val = ctx["_tags"]
    elif name == "Deck":
        val = ctx["_deck"]
    elif name == "Subdeck":
        val = ctx["_deck"].split("::")[-1]
    elif name == "Card":
        val = ctx["_card"]
    elif name == "Type":
        val = ctx["_type"]
    else:
        val = ctx.get(name)
        if val is None:
            return f'<span class="tmpl-err">{{{{{html.escape(tag)}}}}}</span>' if not filters else ""
    if "type" in filters:
        expected = _cloze(val, card_ord + 1, True, only_active=True) if "cloze" in filters else val
        type_state["expected"] = strip_html(expected)
        if answer:
            return f'<div id="typeans-result" data-expected="{html.escape(type_state["expected"], quote=True)}"></div>'
        return '<input id="typeans" type="text" autocomplete="off" autocapitalize="off" spellcheck="false">'
    for f in reversed(filters):
        if f == "cloze":
            val = _cloze(val, card_ord + 1, answer)
        elif f == "text":
            val = strip_html(val)
        elif f == "hint":
            if strip_html(val):
                val = f'<a class="hint" href="#" onclick="this.style.display=\'none\';this.nextElementSibling.style.display=\'block\';return false">Show {html.escape(name)}</a><div class="hint-body" style="display:none">{val}</div>'
        elif f in ("furigana", "kana", "kanji"):
            val = _furigana(val, f)
    return val


def _render(fmt: str, ctx: dict, answer: bool, card_ord: int, type_state: dict) -> str:
    def section(m):
        kind, name, body = m.group(1), m.group(2).strip(), m.group(3)
        key = name.split(":")[-1].strip()
        filled = bool(strip_html(ctx.get(key, "") or "")) or ("<img" in (ctx.get(key) or ""))
        if name.startswith("cloze:") or ":" in name and "cloze" in name.split(":"):
            filled = bool(re.search(r"\{\{c%d::" % (card_ord + 1), ctx.get(key, "") or ""))
        return body if filled == (kind == "#") else ""
    prev = None
    while prev != fmt:
        prev, fmt = fmt, _SECTION.sub(section, fmt)
    return _TAG.sub(lambda m: _apply(m.group(1), ctx, answer, card_ord, type_state), fmt)


def _media(s: str) -> str:
    s = _SRC.sub(lambda m: f'{m.group(1)}"/media/{m.group(3)}"', s)
    return _SOUND.sub(lambda m: f'<audio controls preload="auto" src="/media/{html.escape(m.group(1))}"></audio>', s)


@lru_cache(maxsize=256)
def _notetype(ntid: int, _v: int = 0):
    r = db.conn().execute("SELECT * FROM notetypes WHERE id = ?", (ntid,)).fetchone()
    return dict(name=r["name"], kind=r["kind"], fields=json.loads(r["fields"]),
                templates=json.loads(r["templates"]), css=r["css"])


def clear_cache():
    _notetype.cache_clear()


def render_card(card) -> dict:
    c = db.conn()
    note = c.execute("SELECT * FROM notes WHERE id = ?", (card["note_id"],)).fetchone()
    nt = _notetype(note["notetype_id"])
    deck = c.execute("SELECT name FROM decks WHERE id = ?", (card["deck_id"],)).fetchone()
    vals = json.loads(note["fields"])
    ctx = dict(zip(nt["fields"], vals))
    cloze = nt["kind"] == 1
    tmpl = nt["templates"][0 if cloze else min(card["ord"], len(nt["templates"]) - 1)]
    ctx.update(_tags=note["tags"], _deck=deck["name"] if deck else "", _type=nt["name"], _card=tmpl["name"])
    ts: dict = {}
    q = _render(tmpl["qfmt"], ctx, False, card["ord"], ts)
    a_fmt = tmpl["afmt"].replace("{{FrontSide}}", "\x00FRONT\x00")
    a = _render(a_fmt, ctx, True, card["ord"], ts)
    q_for_back = re.sub(r'<input id="typeans"[^>]*>', "", q)
    a = a.replace("\x00FRONT\x00", q_for_back)
    return {"question": _media(q), "answer": _media(a), "css": nt["css"], "notetype": nt["name"],
            "template": tmpl["name"], "deck": ctx["_deck"], "tags": note["tags"],
            "source_url": note["source_url"], "source_label": note["source_label"],
            "fields": dict(zip(nt["fields"], vals)), "sort_field": strip_html(vals[0])[:200] if vals else ""}

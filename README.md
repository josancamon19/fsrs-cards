# FSRS Cards

A small, fast, local Anki-style flashcard app for one user. It imports `.apkg` files and schedules
reviews with **FSRS-6** (via [py-fsrs](https://github.com/open-spaced-repetition/py-fsrs)). Everything
is stored in SQLite in `./data/anki.db`, and media files go in `./data/media/`.

```bash
./run.sh                 # opens http://127.0.0.1:8000
```

## What it does
- **Import** `.apkg`/`.colpkg` files in both formats: legacy `anki2`/`anki21` and the newer zstd `anki21b`. It brings in
  media, note types, templates and CSS, plus the deck tree. If the file has review history, it can
  replay it through FSRS to rebuild each card's memory state. Importing the same file again keeps your local progress.
  Importing is done from the command line only; the website has no import button, so nothing gets imported by accident:
  `uv run python tools/import_apkg.py deck.apkg --url https://fsrs-cards-8378.fly.dev --password …`
  (add `--no-history` to skip replaying review history; omit `--url` for the local app).
- **Study** cards the way Anki does. New, learning and review cards have daily limits, learning steps and a learn-ahead window.
  Templates support `{{cloze:}}`, `{{type:}}` with a character diff, `{{hint:}}`, conditionals, furigana and `[sound:]`.
  LaTeX `\( \)` and `\[ \]` is rendered with KaTeX, which is bundled locally so it works offline.
  - Each rating button shows the exact interval FSRS will schedule. Fuzz is seeded per card, so the preview matches the real result.
  - Every card shows its live FSRS state: retrievability, stability and difficulty. After each answer a toast
    shows the change: `Good → 1.5mo · S 19.2d → 46.0d · D 6.3 · R was 91%`.
  - Keys: `Space` reveals the answer, then rates Good. `1`–`4` rate Again/Hard/Good/Easy. `U` undoes, `S` skips the card for now (it returns at the end of the session; no review is logged, so FSRS is unaffected), `I` opens card info and `Esc` goes back. Hover a study-bar button to see what it does.
- **Card info** shows the forgetting curve and stability after each review. It also lists the full review log with R at review time,
  elapsed days, S before→after, D, interval and time spent.
- **Stats** cover today's KPIs, true retention vs. desired retention, and card states. Answers are broken down by card state,
  and there are reviews per day stacked by rating, a 30-day forecast, and stability, difficulty and retrievability histograms.
  An **FSRS calibration** plot compares predicted and actual recall. There is also a time-of-day chart, a yearly heatmap, and the model's parameters.
- **Browse** lets you search, filter and sort by S, D or lapses, and suspend or reset cards.
- **Settings** cover desired retention, limits, steps, and custom FSRS weights (you can paste them from Anki).
  To fit weights on your own reviews: `uv sync --extra optimizer` (installs torch), then click *Optimize* in Settings.

- **Spoken answers**: press `M` (or *Mic* in the study bar) and answer each card out loud. Recording starts when a card
  appears and ends when you rate it. In the background the audio is transcribed with OpenAI `gpt-transcribe`, using the
  card text as vocabulary context. Then `gpt-6-luna` cleans it up the way a dictation app would and lists what you were *unsure* about
  and what you *missed* from the reference answer. Only the text is kept: the audio is deleted once transcribed.
  Silent or very short takes (under 1.5s) are skipped. Press `F` to flag an answer to dive into later.
  **Answers** lists every attempt, newest first, with search and filters, and Card info shows a card's attempts over time.
  Needs `OPENAI_API_KEY` on the server (`fly secrets set OPENAI_API_KEY=…`). `TRANSCRIBE_MODEL`/`CLEANUP_MODEL` override the models.
  `GET /api/responses` returns everything as JSON, for later analysis with a model.

## Cards live in the database
The live app's SQLite database (on Fly) is the **source of truth** for every card: content, progress, suspensions,
Bear links and spoken answers. `.apkg` files are only used once, to bring in an outside deck. After that, all
reads and writes go through `tools/cards.py`, which talks to the live app by default (URL from `.fly-app-name`,
password from `.app-password`):
```bash
uv run python tools/cards.py types                         # note types + fields
uv run python tools/cards.py list --q softmax              # find notes
uv run python tools/cards.py show <note id>                # full note as JSON
uv run python tools/cards.py add note.json                 # {"notetype","deck","fields","tags"} (or a list)
uv run python tools/cards.py edit <note id> -f Back=@back.html [--reset]
uv run python tools/cards.py rm <note id>
uv run python tools/cards.py export                        # decks/<deck>.json: content-only snapshot for git history
```
Edited and added notes are marked `edited_at`, so re-importing an old `.apkg` never overwrites them.

## Layout
`app/apkg.py` handles import, `app/sched.py` holds FSRS and the queue, and `app/render.py` renders templates.
`app/main.py` is the API, and `static/` holds the single-page UI. It has no build step.

## Live deployment (Fly.io)
The app runs at **https://fsrs-cards-8378.fly.dev**. It is one machine in `sjc` with a 1 GB volume at `/data`
holding the SQLite DB and media. Fly snapshots the volume daily and keeps 14 days of snapshots. The machine
suspends when idle, so the first request after a pause takes about a second.

```bash
fly deploy --ha=false                           # ship changes (always keep a single machine; SQLite needs one writer)
fly secrets set APP_PASSWORD=new-password       # change the login (signs out every device)
fly ssh console -C "sqlite3 /data/anki.db .dump" > backup.sql   # ad-hoc backup
```
Locally, `./run.sh` runs without a password unless `APP_PASSWORD` is set.

**Install as an app (PWA):** on iPhone, open the site in Safari → Share → *Add to Home Screen*. On Android or desktop
Chrome, use the install icon or *Install app*.

## Backups
Two layers:
1. **Fly volume snapshots:** daily, kept 14 days (`fly volumes snapshots list <vol>`). Fast restores, but they stay inside Fly.
   Moving or forking the volume starts a fresh snapshot history.
2. **Private GitHub repo `josancamon19/fsrs-cards-backups`:** a daily GitHub Action calls the admin-only
   `/api/admin/backup` and commits `snapshot/anki.sql` (plain-text dump) plus `snapshot/media/`. Every commit is a
   verified, restorable copy, and git keeps all days. Run one by hand from the repo's Actions tab, or locally with:
   ```bash
   uv run python tools/backup.py --out ~/Backups/fsrs-cards
   ```
Restore: `sqlite3 anki.db < snapshot/anki.sql`, then put `anki.db` and the media into the data directory (see that repo's README).

## Links back to Bear notes
On the answer side each card can show an **Open in Bear › section** chip (key `O`). It opens
`bear://x-callback-url/open-note?id=…&header=…`, which jumps to that heading in Bear on Mac or iOS.

Ways a note gets its link:
1. **In the deck itself (best for new decks):** add a field named `Source` (or put any `bear://…` URL in a field)
   containing e.g. `bear://x-callback-url/open-note?id=NOTE_ID&header=4.%20PPO%2C%202017`. It is picked up on import.
2. **Hand-curated map:** `tools/maps/math4ml_manual.json` (note id → Bear heading, or `null` for no reference):
   `uv run python tools/bear_link.py --manual tools/maps/math4ml_manual.json --url https://fsrs-cards-8378.fly.dev --password …`
3. **Automatic first pass:** TF-IDF matching against the note's headings, which is useful as a draft for a manual map:
   `uv run python tools/bear_link.py --deck RL --bear-note 0E8B2A3E-… --dry-run --report draft.csv --url … --password …`

Re-importing a deck keeps existing links unless the deck carries its own `Source` field.

## Suspended cards = rewrite queue
Suspend a card from **Card info → Suspend…** and pick a reason (e.g. *List / too many items*, *Ambiguous question*).
The server records when it happened and why. To pull the queue to your Mac:
```bash
uv run python tools/export_suspended.py --url https://fsrs-cards-8378.fly.dev --password …   # → review/suspended.md + .json
```
`review/suspended.json` has the original HTML fields and note ids, so the cards can be rewritten and re-imported later.

## Imports are code-only
The website has no import button. On the server, `POST /api/import`, `DELETE /api/decks/{id}` and
`DELETE /api/notes/{id}` also need the `ADMIN_TOKEN` secret, sent as the `X-Admin-Token` header, on top of the login.
That keeps them reachable only from your machine:
```bash
uv run python tools/import_apkg.py deck.apkg --url https://fsrs-cards-8378.fly.dev --password …   # token read from .admin-token
```

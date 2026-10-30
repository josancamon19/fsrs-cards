# Notes for coding agents

FSRS Cards: a single-user FSRS-6 flashcard app. FastAPI + SQLite in `app/`, a no-build SPA in `static/`, model
prompts in `prompts/*.md`. Live on Fly (`fsrs-cards-8378`, one machine, volume mounted at `/data`). The live
database is the source of truth for cards; edit them through the API or `tools/cards.py`, never by re-importing.

## Back up often

The database holds the review history, spoken answers and conversations; none of it can be rebuilt.

- Automatic: a daily GitHub Action in the private repo `josancamon19/fsrs-cards-backups` commits a verified SQL dump
  plus media, and Fly keeps 14 days of volume snapshots.
- **Take a fresh backup before anything that could damage data**: every deploy, schema changes, bulk card edits,
  imports, deletes, or work on the Fly machine or volume:

      gh workflow run backup.yml -R josancamon19/fsrs-cards-backups    # then: gh run watch -R josancamon19/fsrs-cards-backups

  or a local copy: `uv run python tools/backup.py --out ~/Backups/fsrs-cards`.
- Restore steps are in the backups repo's README. If APP_PASSWORD or ADMIN_TOKEN change, update that repo's secrets.

## Rules

- This repo is public. Never commit `.env`, `.app-password`, `.admin-token`, `.fly-app-name` or `data/`, and never
  put database content (answers, conversations, backups) here.
- Test big changes locally first (`./run.sh`, or `ANKI_FSRS_DATA=<copy of a backup>`) and ask before deploying.
  Deploy with `fly deploy --ha=false`.
- Commit and push each finished change.
- Prompts: edit `prompts/*.md` (loaded on each use by `app/prompts.py`), not strings in code.

#!/usr/bin/env bash
# Start FSRS Cards on http://127.0.0.1:8000 (data lives in ./data unless ANKI_FSRS_DATA is set)
cd "$(dirname "$0")"
PORT="${PORT:-8000}"
( sleep 1.2 && open "http://127.0.0.1:$PORT" >/dev/null 2>&1 ) &
exec uv run uvicorn app.main:app --host 127.0.0.1 --port "$PORT" --log-level warning

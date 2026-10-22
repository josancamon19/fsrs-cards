"""Import an .apkg/.colpkg into the app. This is the only way to import (the website has no import button).

  uv run python tools/import_apkg.py deck.apkg --url https://fsrs-cards-8378.fly.dev --password ...
  uv run python tools/import_apkg.py deck.apkg                      # local app on :8000

The server only accepts imports with its ADMIN_TOKEN (X-Admin-Token header). It is read from --admin-token,
$ADMIN_TOKEN, or the git-ignored file .admin-token next to this repo's fly.toml.

Re-importing keeps local progress. --no-history skips replaying the deck's review log into FSRS.
"""
import argparse
import json
import os
import urllib.request
import uuid
from pathlib import Path

from bear_link import Api


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file")
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    ap.add_argument("--password")
    ap.add_argument("--no-history", action="store_true")
    ap.add_argument("--admin-token")
    a = ap.parse_args()

    token_file = Path(__file__).resolve().parent.parent / ".admin-token"
    token = a.admin_token or os.environ.get("ADMIN_TOKEN") or (token_file.read_text().strip() if token_file.exists() else "")
    path = Path(a.file)
    api = Api(a.url, a.password)
    boundary = uuid.uuid4().hex
    body = (f'--{boundary}\r\nContent-Disposition: form-data; name="history"\r\n\r\n{str(not a.no_history).lower()}\r\n'
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
            "Content-Type: application/octet-stream\r\n\r\n").encode() + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(api.base + "/api/import", data=body,
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}",
                                          "X-Admin-Token": token})
    r = json.load(api.opener.open(req))
    print(f"{path.name} → {a.url}: {r['cards']} new cards, {r['skipped_cards']} already present, "
          f"{r['notes']} notes, {r['media']} media, {r['reviews']} reviews replayed · {r['seconds']}s")


if __name__ == "__main__":
    main()

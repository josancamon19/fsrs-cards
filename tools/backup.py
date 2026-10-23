"""Download a full backup of the app and unpack it into a folder, then prove it restores.

  uv run python tools/backup.py --out ~/Backups/fsrs-cards          # live app (URL/password/admin token from the repo files)
  python backup.py --out .                                           # in the private backups repo (env vars, stdlib only)

The folder gets anki.sql (plain-text dump of the database) and media/. Committing that folder to a private git repo
every day keeps full history cheaply, since git stores only what changed. Restore:

  sqlite3 anki.db < anki.sql         # then put anki.db and media/ in the app's data directory (/data on Fly)

Credentials: --url/--password/--admin-token, else $APP_URL/$APP_PASSWORD/$ADMIN_TOKEN, else this repo's
.fly-app-name/.app-password/.admin-token.
"""
import argparse
import io
import json
import os
import shutil
import sqlite3
import sys
import tarfile
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _file(name: str) -> str:
    p = ROOT / name
    return p.read_text().strip() if p.exists() else ""


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default=os.environ.get("APP_URL") or (f"https://{_file('.fly-app-name')}.fly.dev" if _file(".fly-app-name") else ""))
    ap.add_argument("--password", default=os.environ.get("APP_PASSWORD") or _file(".app-password"))
    ap.add_argument("--admin-token", default=os.environ.get("ADMIN_TOKEN") or _file(".admin-token"))
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    if not a.url:
        sys.exit("no --url / $APP_URL")

    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))
    if a.password:
        opener.open(urllib.request.Request(a.url.rstrip("/") + "/api/login", data=json.dumps({"password": a.password}).encode(),
                                           headers={"Content-Type": "application/json"}), timeout=60)
    req = urllib.request.Request(a.url.rstrip("/") + "/api/admin/backup", headers={"X-Admin-Token": a.admin_token})
    archive = opener.open(req, timeout=300).read()

    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
        names = tar.getnames()
        if "anki.sql" not in names or any(n.startswith("/") or ".." in n for n in names):
            sys.exit("unexpected archive contents")
        sql = tar.extractfile("anki.sql").read().decode()
        media = {n[len("media/"):]: tar.extractfile(n).read() for n in names if n.startswith("media/") and tar.getmember(n).isfile()}

    # prove the dump restores before replacing the previous backup
    test = sqlite3.connect(":memory:")
    test.executescript(sql)
    ok = test.execute("PRAGMA integrity_check").fetchone()[0]
    counts = {t: test.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("notes", "cards", "revlog", "responses", "chats")
              if test.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,)).fetchone()}
    if ok != "ok" or not counts.get("cards"):
        sys.exit(f"backup failed verification: integrity={ok}, counts={counts}")

    out = Path(a.out).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    (out / "anki.sql").write_text(sql)
    mdir = out / "media"
    if mdir.exists():
        shutil.rmtree(mdir)
    mdir.mkdir()
    for name, data in media.items():
        (mdir / Path(name).name).write_bytes(data)
    print(f"backup ok → {out}: {len(sql) / 1e6:.1f} MB sql, {len(media)} media files, "
          + ", ".join(f"{v} {k}" for k, v in counts.items()))


if __name__ == "__main__":
    main()

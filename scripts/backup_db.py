"""MongoDB backup:  python -m scripts.backup_db

The bot also runs this by itself every AUTO_BACKUP_HOURS and sends the file to the
owner on Telegram (see helper/scheduler.py), so the manual run is optional now.

Two ways of dumping, chosen automatically:
  * `mongodump` (MongoDB Database Tools) when it is installed -> restore with mongorestore
  * otherwise a built-in Python export, one <collection>.jsonl per collection in
    canonical extended JSON -> restore with mongoimport. The default Docker image has
    no mongodump, which is why this fallback exists.

Settings (environment variables, all optional):
    BACKUP_DIR        where backups go (default: backups)
    BACKUP_COMPRESS   True/False, .tar.gz or plain folder (default: True)
    BACKUP_KEEP       keep only the newest N backups, 0 = keep all (default: 7)
"""
import os
import shutil
import subprocess
import sys
import tarfile
from datetime import datetime, timezone

from config import DB_NAME, DB_URI

BACKUP_DIR = os.getenv("BACKUP_DIR", "backups")
COMPRESS = os.getenv("BACKUP_COMPRESS", "True").strip().lower() in ("1", "true", "yes")
KEEP = int(os.getenv("BACKUP_KEEP", "7") or 0)


class BackupError(Exception):
    """Backup failed; the message is safe to show (it never contains the DB URI)."""


def prune(directory, prefix, keep):
    """Delete all but the newest `keep` backups of this database."""
    if keep <= 0:
        return []
    mine = sorted(n for n in os.listdir(directory) if n.startswith(prefix + "_"))
    removed = []
    for name in mine[:-keep]:
        path = os.path.join(directory, name)
        shutil.rmtree(path) if os.path.isdir(path) else os.remove(path)
        removed.append(name)
    return removed


def _dump_with_mongodump(out_dir):
    try:
        subprocess.run(["mongodump", "--uri", DB_URI, "--db", DB_NAME, "--out", out_dir],
                       check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        # not echoing the command or its output: both can contain the URI
        raise BackupError(f"mongodump failed (exit code {e.returncode})")


def _dump_with_python(out_dir):
    try:
        from bson import json_util
        from pymongo import MongoClient
    except ImportError:
        raise BackupError("pymongo is not installed")
    os.makedirs(out_dir, exist_ok=True)
    client = MongoClient(DB_URI, serverSelectionTimeoutMS=20000)
    try:
        db = client[DB_NAME]
        for name in db.list_collection_names():
            if name.startswith("system."):
                continue
            with open(os.path.join(out_dir, f"{name}.jsonl"), "w", encoding="utf-8") as fh:
                for doc in db[name].find({}):
                    fh.write(json_util.dumps(doc, json_options=json_util.CANONICAL_JSON_OPTIONS) + "\n")
    except Exception as e:
        raise BackupError(f"Python export failed: {type(e).__name__}")  # message could echo the URI
    finally:
        client.close()


def make_backup(compress=None):
    """Create one backup and return (path, method). Raises BackupError. Blocking: run it in a thread.

    compress=True always gives a single .tar.gz file (what the bot needs to send it on Telegram).
    """
    if not DB_URI:
        raise BackupError("DB_URI is empty")
    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    folder = f"{DB_NAME}_{stamp}"
    out_dir = os.path.join(BACKUP_DIR, folder)

    method = "mongodump" if shutil.which("mongodump") else "python"
    try:
        (_dump_with_mongodump if method == "mongodump" else _dump_with_python)(out_dir)
    except BackupError:
        shutil.rmtree(out_dir, ignore_errors=True)
        raise

    final = out_dir
    if COMPRESS if compress is None else compress:
        final = f"{out_dir}.tar.gz"
        with tarfile.open(final, "w:gz") as tar:
            tar.add(out_dir, arcname=folder)
        shutil.rmtree(out_dir)

    prune(BACKUP_DIR, DB_NAME, KEEP)
    return final, method


def create_backup():
    """Command-line entry point."""
    print("🔄 Starting MongoDB backup...")
    try:
        final, method = make_backup()
    except BackupError as e:
        print(f"❌ {e}")
        return 1
    print(f"✅ Backup created ({method}): {final}")
    return 0


if __name__ == "__main__":
    sys.exit(create_backup())

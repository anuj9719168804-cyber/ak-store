#!/usr/bin/env bash
# File-Store-Pro: one-command start for VPS / panel hosts (Pterodactyl, etc.)
# Docker and Heroku do not need this; they run `python main.py` directly.
set -e
cd "$(dirname "$0")"
pip install -r requirements.txt --no-cache-dir --quiet
exec python3 main.py

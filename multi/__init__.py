"""Multi-user bot creation system (ported from Multi-FileStoreBot).

This package adds a per-user bot-creation platform on top of File-Store-Pro:
  • Users create their own file-store bots via the controller (Pro) bot.
  • Each user bot runs as an independent Pyrogram client in the same process.
  • Per-bot state is isolated in namespaced MongoDB collections.

Sub-modules:
  security  – Fernet token encryption (gracefully degrades to plain-text)
  registry  – Bot registry (RegistryDB) + per-worker DB (WorkerDB)
  engine    – Dynamic multi-client manager (WorkerEngine singleton)
  link_gen  – /genlink /batch /custom_batch /flink for worker bots
"""

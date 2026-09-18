"""On-disk layout for everything analysis_ai generates (all under DATA_DIR, gitignored)."""
import json
import os
from pathlib import Path

from . import config

D = config.DATA_DIR
SNAPSHOT = D / "snapshot"          # mirror of the notes app's structure + note text
TRANSCRIPTS = D / "transcripts"    # our own Whisper transcripts, one JSON per media note
CARDS = D / "cards"                # per-note study cards
VAULT = D / "vault"                # human-readable markdown (Obsidian-compatible)
INDEX_DB = D / "index.db"          # retrieval index (SQLite)
LOGS = D / "logs"


def ensure_dirs() -> None:
    for p in (SNAPSHOT / "notes", TRANSCRIPTS, CARDS, VAULT, LOGS):
        p.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, obj) -> None:
    """Atomic write: a crash mid-write can never leave a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def read_json(path: Path, default=None):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))

"""Transcribe audio/video notes with Whisper, in a throwaway container.

The container is built from the notes app's worker image (it already has
faster-whisper and CUDA). The uploads folder is mounted READ-ONLY; output goes
to our own data/transcripts/. Manual trigger only -- nothing runs on its own.
"""
import subprocess
import time
from pathlib import Path

from . import config, store

SCRIPT_DIR = config.PACKAGE_ROOT / "scripts"


def find_media(uploads: Path, note: dict) -> Path | None:
    folder = uploads / note["id"]
    name = (note.get("media") or {}).get("original_filename")
    if name and (folder / name).exists():
        return folder / name
    files = [p for p in folder.glob("*") if p.is_file()] if folder.exists() else []
    return files[0] if len(files) == 1 else None


def transcribe_pending(cfg: dict, notes: list[dict], only: str | None = None) -> None:
    uploads = Path(cfg["uploads_dir"])
    store.ensure_dirs()
    todo = [
        n for n in notes
        if n["type"] in ("audio", "video")
        and not (store.TRANSCRIPTS / f"{n['id']}.json").exists()
        and (only is None or n["id"].startswith(only))
    ]
    print(f"{len(todo)} media note(s) need transcripts", flush=True)
    for i, note in enumerate(todo, 1):
        media = find_media(uploads, note)
        label = f"[{i}/{len(todo)}] {note['project']} / {note['title']}"
        if media is None:
            print(f"{label}: media file not found under {uploads / note['id']}, skipping", flush=True)
            continue
        print(f"{label}: transcribing {media.name}", flush=True)
        started = time.time()
        cmd = [
            "docker", "run", "--rm", "--gpus", "all",
            "-v", f"{uploads}:/media:ro",
            "-v", f"{SCRIPT_DIR}:/scripts:ro",
            "-v", f"{store.TRANSCRIPTS}:/out",
            "-v", "analysis_ai_whisper_cache:/root/.cache/huggingface",
            cfg["docker_image"],
            "python", "/scripts/transcribe.py",
            f"/media/{note['id']}/{media.name}", f"/out/{note['id']}.json",
            "--model", cfg["whisper_model"], "--language", cfg["whisper_language"],
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        with (store.LOGS / "transcribe.log").open("a", encoding="utf-8") as log:
            log.write(f"\n=== {label} rc={result.returncode}\n{result.stdout[-2000:]}\n{result.stderr[-2000:]}\n")
        status = "ok" if result.returncode == 0 else f"FAILED rc={result.returncode} (see logs/transcribe.log)"
        print(f"{label}: {status} in {time.time() - started:.0f}s", flush=True)


def load(note_id: str) -> dict | None:
    return store.read_json(store.TRANSCRIPTS / f"{note_id}.json")

"""Transcribe audio/video notes with Whisper. Manual trigger only.

Two ways to run the same scripts/transcribe.py, chosen by cfg["transcribe_mode"]:
  docker -- a throwaway container from the notes app's worker image (used when
            analysis_ai runs on the host). uploads/ is mounted READ-ONLY.
  local  -- directly in this process tree (used inside the analysis_ai
            container, which has faster-whisper and CUDA and mounts uploads :ro).
Either way the script runs as a separate process, so GPU memory is released
the moment it exits and a running job can be killed to cancel.
"""
import os
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from . import config, ollama, store
from .progress import Cancelled, Ctx

SCRIPT_DIR = config.PACKAGE_ROOT / "scripts"


def find_media(uploads: Path, note: dict) -> Path | None:
    folder = uploads / note["id"]
    name = (note.get("media") or {}).get("original_filename")
    if name and (folder / name).exists():
        return folder / name
    files = [p for p in folder.glob("*") if p.is_file()] if folder.exists() else []
    return files[0] if len(files) == 1 else None


def mode(cfg: dict) -> str:
    if cfg["transcribe_mode"] != "auto":
        return cfg["transcribe_mode"]
    return "local" if os.environ.get("AAI_IN_CONTAINER") else "docker"


DURATIONS = store.D / "durations.json"  # cache of ffprobe results, keyed by note id


def duration_seconds(cfg: dict, note: dict) -> float | None:
    """How long a recording is. The notes app only fills this in when IT transcribes a
    note, which it no longer does on its own, so fall back to our own transcript and
    then to reading the (read-only) file with ffprobe. None if nothing works."""
    media = note.get("media") or {}
    if media.get("duration_seconds"):
        return media["duration_seconds"]
    transcript = load(note["id"])
    if transcript and transcript.get("duration_seconds"):
        return transcript["duration_seconds"]
    if not media:
        return None
    cache = store.read_json(DURATIONS, {})
    key = f"{media.get('original_filename')}:{media.get('size_bytes')}"  # a re-upload changes this
    hit = cache.get(note["id"])
    if hit and hit["key"] == key:
        return hit["seconds"]
    path = find_media(Path(cfg["uploads_dir"]), note)
    if path is None or shutil.which("ffprobe") is None:
        return None
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                             capture_output=True, text=True, timeout=30)
        seconds = float(out.stdout.strip())
    except (subprocess.SubprocessError, ValueError, OSError):
        return None
    cache[note["id"]] = {"key": key, "seconds": seconds}
    store.write_json(DURATIONS, cache)
    return seconds


def estimate_seconds(cfg: dict, note: dict) -> float | None:
    """Rough wall-clock estimate: large-v3 measured at ~0.17x realtime on the idle GPU."""
    duration = duration_seconds(cfg, note)
    return duration * 0.17 if duration else None


def _command(cfg: dict, note: dict, media: Path, name: str) -> list[str]:
    tail = ["--model", cfg["whisper_model"], "--language", cfg["whisper_language"]]
    if mode(cfg) == "local":
        return [sys.executable, str(SCRIPT_DIR / "transcribe.py"), str(media), str(store.TRANSCRIPTS / f"{note['id']}.json.part"), *tail, "--force"]
    return [
        "docker", "run", "--rm", "--name", name, "--gpus", "all",
        "-v", f"{Path(cfg['uploads_dir'])}:/media:ro",
        "-v", f"{SCRIPT_DIR}:/scripts:ro",
        "-v", f"{store.TRANSCRIPTS}:/out",
        "-v", "analysis_ai_whisper_cache:/root/.cache/huggingface",
        cfg["docker_image"],
        "python", "/scripts/transcribe.py",
        f"/media/{note['id']}/{media.name}", f"/out/{note['id']}.json.part", *tail, "--force",
    ]


def _run_cancellable(cmd: list[str], ctx: Ctx, kill) -> int:
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace")

    def pump():
        for line in proc.stdout:
            line = line.strip()
            if line and "HF Hub" not in line:
                ctx.log("    " + line)

    reader = threading.Thread(target=pump, daemon=True)
    reader.start()
    try:
        while proc.poll() is None:
            ctx.check()
            time.sleep(0.5)
    except Cancelled:
        kill(proc)
        proc.wait()
        raise
    reader.join(timeout=5)
    return proc.returncode


def transcribe_pending(cfg: dict, notes: list[dict], *, only: str | None = None, ids: set[str] | None = None,
                       force: bool = False, ctx: Ctx | None = None) -> dict:
    ctx = ctx or Ctx()
    uploads = Path(cfg["uploads_dir"])
    store.ensure_dirs()
    todo = [
        n for n in notes
        if n["type"] in ("audio", "video")
        and (force or not (store.TRANSCRIPTS / f"{n['id']}.json").exists())
        and (only is None or n["id"].startswith(only))
        and (ids is None or n["id"] in ids)
    ]
    ctx.log(f"{len(todo)} media note(s) to transcribe (mode: {mode(cfg)}, model: {cfg['whisper_model']}, language: {cfg['whisper_language']})")
    counts = {"ok": 0, "failed": 0, "missing-file": 0}
    if todo:
        ollama.unload_all(cfg)  # free VRAM for Whisper

    for i, note in enumerate(todo):
        ctx.check()
        label = f"{note['project']} / {note['title']}"
        ctx.progress(i, len(todo), label)
        media = find_media(uploads, note)
        if media is None:
            ctx.log(f"[{i + 1}/{len(todo)}] {label}: media file not found under {uploads / note['id']}, skipping")
            counts["missing-file"] += 1
            continue
        ctx.log(f"[{i + 1}/{len(todo)}] {label}: transcribing {media.name}")
        started = time.time()
        name = f"aai-transcribe-{note['id'][:8]}"
        part = store.TRANSCRIPTS / f"{note['id']}.json.part"
        part.unlink(missing_ok=True)

        def kill(proc, name=name):
            if mode(cfg) == "docker":
                subprocess.run(["docker", "stop", name], capture_output=True)
            proc.terminate()

        rc = _run_cancellable(_command(cfg, note, media, name), ctx, kill)
        final = store.TRANSCRIPTS / f"{note['id']}.json"
        if rc == 0 and part.exists():
            if final.exists():  # never overwrite silently: keep the previous transcript
                prev = store.TRANSCRIPTS / "previous"
                prev.mkdir(exist_ok=True)
                shutil.move(str(final), prev / f"{note['id']}-{datetime.now():%Y%m%d-%H%M%S}.json")
            os.replace(part, final)
            counts["ok"] += 1
            ctx.log(f"    done in {time.time() - started:.0f}s")
        else:
            part.unlink(missing_ok=True)
            counts["failed"] += 1
            ctx.log(f"    FAILED (exit {rc}) -- see the lines above")
    ctx.progress(len(todo), len(todo), "")
    ctx.log(f"summary: {counts}")
    problems = []
    if counts["missing-file"]:
        problems.append(f"{counts['missing-file']} recording(s) have no uploaded file in the notes app "
                        "(the upload probably never finished) -- re-upload them there first")
    if counts["failed"]:
        problems.append(f"{counts['failed']} transcription(s) failed -- see the log")
    if problems:  # a job that skipped or failed work must not show as "done"
        raise RuntimeError("; ".join(problems))
    return counts


def load(note_id: str) -> dict | None:
    return store.read_json(store.TRANSCRIPTS / f"{note_id}.json")

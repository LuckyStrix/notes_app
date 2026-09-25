"""Backups of data/ -- the transcripts, summary cards, overviews and search
index this tool generates.

They go into config.BACKUPS_DIR, which by default is the same host folder the
notes app writes its database dumps to. Every archive gets a `.meta.json`
sidecar, and retention only ever deletes archives that have one, so nothing
else in that folder (the notes app's dumps, anything made by hand) is at risk.

Archives are written under a `.partial` name and renamed only once they have
been read back and verified, so a file with a real name is always a complete,
checked backup.
"""
import hashlib
import os
import tarfile
import time
import zlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import config, store

PREFIX = "analysis_ai_"
META_SUFFIX = ".meta.json"
STATUS_FILE = "analysis_ai.status.json"
INTERVALS = {"daily": timedelta(days=1), "weekly": timedelta(days=7)}
# Regenerated on every run and occasionally large -- restoring them would tell
# you nothing you cannot see in the app.
EXCLUDE = {"logs"}


class BackupError(RuntimeError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


class _HashingWriter:
    """Hashes the archive as tarfile writes it, so the checksum costs no extra pass."""

    def __init__(self, fh):
        self._fh = fh
        self.digest = hashlib.sha256()

    def write(self, data) -> int:
        self.digest.update(data)
        return self._fh.write(data)

    def flush(self) -> None:
        self._fh.flush()


def _status_path() -> Path:
    return config.BACKUPS_DIR / STATUS_FILE


def read_status() -> dict:
    return store.read_json(_status_path(), {}) or {}


def _write_status(status: dict) -> None:
    previous = read_status()
    if status.get("status") != "ok" and previous.get("last_success_at"):
        status = {**status, "last_success_at": previous["last_success_at"]}
    try:
        store.write_json(_status_path(), status)
    except OSError:
        pass  # a backup that worked must not report as failed because the status note didn't save


def last_success_at() -> datetime | None:
    raw = read_status().get("last_success_at")
    try:
        return datetime.fromisoformat(raw) if raw else None
    except (TypeError, ValueError):
        return None


def is_due(frequency: str) -> bool:
    last = last_success_at()
    return last is None or _now() - last >= INTERVALS.get(frequency, INTERVALS["daily"])


def _tracked() -> list[tuple[Path, dict]]:
    """Archives this module made, oldest first -- i.e. the ones with a sidecar."""
    found = []
    for meta_path in config.BACKUPS_DIR.glob(f"*{META_SUFFIX}"):
        meta = store.read_json(meta_path, None)
        if not isinstance(meta, dict) or meta.get("kind") != "analysis_ai":
            continue
        archive = meta_path.with_name(meta_path.name[: -len(META_SUFFIX)])
        if archive.exists():
            found.append((archive, meta))
    found.sort(key=lambda item: item[1].get("created_at", ""))
    return found


def _prune(keep: int) -> list[str]:
    removed = []
    tracked = _tracked()
    for archive, _meta in tracked[: max(0, len(tracked) - keep)]:
        try:
            archive.unlink()
            archive.with_name(archive.name + META_SUFFIX).unlink(missing_ok=True)
            removed.append(archive.name)
        except OSError:
            pass  # a file we cannot delete is no reason to fail the backup that just succeeded
    return removed


def _validate(path: Path) -> int:
    """Walks every member, so a truncated or corrupt archive fails here rather
    than on the day it is needed. Returns how many files are in it."""
    try:
        with tarfile.open(path, "r:gz") as tar:
            return sum(1 for member in tar if member.isfile())
    except (tarfile.TarError, OSError, EOFError, zlib.error) as exc:
        raise BackupError(f"archive is not a readable tar.gz: {exc}") from exc


def run(cfg: dict | None = None, ctx=None) -> dict:
    """Archive -> validate -> publish -> prune. Returns the sidecar."""
    cfg = cfg or config.load()
    log = ctx.log if ctx else (lambda _message: None)
    if not config.BACKUPS_DIR.is_dir():
        raise BackupError(
            f"Backup folder {config.BACKUPS_DIR} is not mounted. Add an AAI_BACKUP_LOCATION volume "
            f"(see analysis_ai/docker-compose.yml) and restart."
        )
    if not config.DATA_DIR.is_dir():
        raise BackupError(f"Nothing to back up: {config.DATA_DIR} does not exist")

    started = time.monotonic()
    final = config.BACKUPS_DIR / f"{PREFIX}{_now().strftime('%Y%m%d_%H%M%S')}.tar.gz"
    partial = final.with_name(final.name + ".partial")
    log(f"Archiving {config.DATA_DIR} -> {final.name}")
    try:
        with partial.open("wb") as raw:
            writer = _HashingWriter(raw)
            with tarfile.open(fileobj=writer, mode="w|gz") as tar:
                for entry in sorted(config.DATA_DIR.iterdir()):
                    if entry.name in EXCLUDE:
                        continue
                    tar.add(entry, arcname=f"data/{entry.name}")
            checksum = writer.digest.hexdigest()
        file_count = _validate(partial)
    except Exception as exc:
        partial.unlink(missing_ok=True)
        _write_status({"status": "failed", "error": f"{type(exc).__name__}: {exc}",
                       "last_run_at": _now().isoformat()})
        raise

    os.replace(partial, final)
    meta = {
        "kind": "analysis_ai",
        "file": final.name,
        "created_at": _now().isoformat(),
        "size_bytes": final.stat().st_size,
        "sha256": checksum,
        "validated": True,
        "file_count": file_count,
        "duration_seconds": round(time.monotonic() - started, 1),
    }
    store.write_json(final.with_name(final.name + META_SUFFIX), meta)
    pruned = _prune(int(cfg["backup_keep"]))
    _write_status({"status": "ok", "error": None, "file": final.name, "size_bytes": meta["size_bytes"],
                   "pruned": pruned, "last_run_at": meta["created_at"], "last_success_at": meta["created_at"]})
    log(f"Backed up {file_count} files ({meta['size_bytes'] / 1e6:.1f} MB), checked OK")
    return meta


def listing() -> dict:
    """What the Settings tab shows."""
    if not config.BACKUPS_DIR.is_dir():
        return {"mounted": False, "directory": str(config.BACKUPS_DIR), "backups": [], "status": {}}
    return {
        "mounted": True,
        "directory": str(config.BACKUPS_DIR),
        "backups": [meta for _archive, meta in reversed(_tracked())],
        "status": read_status(),
    }

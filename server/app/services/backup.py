"""Managed backups: a scheduled `pg_dump` of the database, plus an on-demand,
incremental sync of the media files the database references.

Everything lands in /backups, a bind mount of the host's backups/ folder (see
BACKUP_LOCATION in docker-compose.yml). Each database dump this module writes
gets a `.meta.json` sidecar next to it, and retention only ever deletes dumps
that have one -- so hand-made dumps dropped in the same folder are never touched.
The media copy lives in its own media/ subfolder, which retention never looks at.

Everything is written to a `.partial` file and renamed only after it passes
validation, so a file with a real name is always a complete, verified copy.
"""
import gzip
import hashlib
import json
import os
import subprocess
import time
import zlib
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse

from app.config import settings as app_config
from app.services.storage import resolve_within

BACKUPS_DIR = Path(os.environ.get("BACKUP_DIR", "/backups"))
MEDIA_DIR_NAME = "media"
MEDIA_MANIFEST = "MANIFEST.json"

DB_PREFIX = "notes_app_db_"
META_SUFFIX = ".meta.json"
STATUS_FILES = {"db": "notes_app_db.status.json", "media": "notes_app_media.status.json"}

# pg_dump writes this as the very last thing in a plain-text dump, so its
# absence means the dump was cut short (disk full, container killed mid-run)
# even though the gzip stream itself may still be intact.
DUMP_HEADER = b"PostgreSQL database dump"
DUMP_FOOTER = b"PostgreSQL database dump complete"


class BackupError(RuntimeError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp() -> str:
    return _now().strftime("%Y%m%d_%H%M%S")


def _require_dir() -> None:
    if not BACKUPS_DIR.is_dir():
        raise BackupError(
            f"Backup folder {BACKUPS_DIR} is not mounted. Add a BACKUP_LOCATION volume to the "
            f"worker service (see docker-compose.yml) and restart it."
        )


class _HashingWriter:
    """File wrapper that sha256s everything written through it, so the
    checksum comes for free instead of costing a second pass over the file."""

    def __init__(self, fh):
        self._fh = fh
        self.digest = hashlib.sha256()

    def write(self, data) -> int:
        self.digest.update(data)
        return self._fh.write(data)

    def flush(self) -> None:
        self._fh.flush()


def pg_dump_command() -> tuple[list[str], dict[str, str]]:
    """Builds a pg_dump invocation from DATABASE_URL. The password goes
    through PGPASSWORD (not argv) so it doesn't show up in `docker top`/`ps`
    output inside the container."""
    parsed = urlparse(app_config.database_url.replace("postgresql+asyncpg", "postgresql", 1))
    dbname = parsed.path.lstrip("/")
    if not parsed.hostname or not dbname:
        raise BackupError("DATABASE_URL is missing a host or database name")
    args = [
        "pg_dump",
        "-h", parsed.hostname,
        "-p", str(parsed.port or 5432),
        "-U", unquote(parsed.username or ""),
        dbname,
    ]
    env = {**os.environ, "PGPASSWORD": unquote(parsed.password or "")}
    return args, env


# ---- validation -------------------------------------------------------------
def _validate_sql_gz(path: Path) -> None:
    """Decompresses the dump to confirm the gzip stream is complete (CRC and
    length are checked at the end of the stream) and that it both starts and
    ends like a pg_dump."""
    decompressor = zlib.decompressobj(31)  # 31 = gzip container
    head = b""
    tail = b""
    try:
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                plain = decompressor.decompress(chunk)
                if len(head) < len(DUMP_HEADER) + 4096:
                    head += plain[:4096]
                if plain:
                    tail = (tail + plain[-4096:])[-4096:]
            tail = (tail + decompressor.flush())[-4096:]
    except zlib.error as exc:
        raise BackupError(f"archive is not a readable gzip stream: {exc}") from exc
    if not decompressor.eof:
        raise BackupError("gzip stream ends early -- the dump was truncated")
    if DUMP_HEADER not in head:
        raise BackupError("dump does not start like a pg_dump")
    if DUMP_FOOTER not in tail:
        raise BackupError("dump has no completion marker -- pg_dump did not finish")


# ---- sidecars, status, retention --------------------------------------------
def _write_meta(path: Path, meta: dict) -> None:
    path.with_name(path.name + META_SUFFIX).write_text(json.dumps(meta, indent=1), encoding="utf-8")


def _read_meta(meta_path: Path) -> dict | None:
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return meta if isinstance(meta, dict) else None


def _write_status(kind: str, status: dict) -> None:
    previous = _read_status(kind)
    if status.get("status") != "ok" and previous.get("last_success_at"):
        status = {**status, "last_success_at": previous["last_success_at"]}
    try:
        (BACKUPS_DIR / STATUS_FILES[kind]).write_text(json.dumps(status, indent=1), encoding="utf-8")
    except OSError:
        pass  # a backup that worked must not be reported as failed just because the status note didn't save


def _read_status(kind: str) -> dict:
    try:
        value = json.loads((BACKUPS_DIR / STATUS_FILES[kind]).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def last_success_at(kind: str) -> datetime | None:
    raw = _read_status(kind).get("last_success_at")
    try:
        return datetime.fromisoformat(raw) if raw else None
    except ValueError:
        return None


def _tracked(kind: str) -> list[tuple[Path, dict]]:
    """Archives this module created, oldest first -- i.e. only ones with a
    sidecar. Anything else in the folder (hand-made dumps) is invisible here,
    which is what keeps retention from deleting it."""
    found = []
    for meta_path in BACKUPS_DIR.glob(f"*{META_SUFFIX}"):
        meta = _read_meta(meta_path)
        if not meta or meta.get("kind") != kind:
            continue
        archive = meta_path.with_name(meta_path.name[: -len(META_SUFFIX)])
        if archive.exists():
            found.append((archive, meta))
    found.sort(key=lambda item: item[1].get("created_at", ""))
    return found


def _prune(kind: str, keep: int) -> list[str]:
    removed = []
    tracked = _tracked(kind)
    for archive, _meta in tracked[: max(0, len(tracked) - keep)]:
        try:
            archive.unlink()
            archive.with_name(archive.name + META_SUFFIX).unlink(missing_ok=True)
            removed.append(archive.name)
        except OSError:
            pass  # a file we cannot delete is not a reason to fail the backup that just succeeded
    return removed


# ---- the backups themselves --------------------------------------------------
def run_db_backup(keep: int, source: str = "manual") -> dict:
    """pg_dump -> gzip -> validate -> publish -> prune. Returns the sidecar."""
    _require_dir()
    started = time.monotonic()
    final = BACKUPS_DIR / f"{DB_PREFIX}{_timestamp()}.sql.gz"
    partial = final.with_name(final.name + ".partial")
    args, env = pg_dump_command()

    try:
        with partial.open("wb") as raw:
            writer = _HashingWriter(raw)
            process = subprocess.Popen(args, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            with gzip.GzipFile(fileobj=writer, mode="wb") as gz:
                assert process.stdout
                for chunk in iter(lambda: process.stdout.read(1 << 20), b""):
                    gz.write(chunk)
            stderr = process.stderr.read().decode(errors="replace") if process.stderr else ""
            if process.wait() != 0:
                raise BackupError(f"pg_dump failed: {stderr.strip() or 'no output'}")
            checksum = writer.digest.hexdigest()
        _validate_sql_gz(partial)
    except Exception as exc:
        partial.unlink(missing_ok=True)
        _write_status("db", {"status": "failed", "error": str(exc), "source": source,
                             "last_run_at": _now().isoformat()})
        raise

    os.replace(partial, final)
    meta = {
        "kind": "db",
        "file": final.name,
        "source": source,
        "created_at": _now().isoformat(),
        "size_bytes": final.stat().st_size,
        "sha256": checksum,
        "validated": True,
        "duration_seconds": round(time.monotonic() - started, 1),
    }
    _write_meta(final, meta)
    pruned = _prune("db", keep)
    _write_status("db", {"status": "ok", "error": None, "source": source, "file": final.name,
                         "size_bytes": meta["size_bytes"], "pruned": pruned,
                         "last_run_at": meta["created_at"], "last_success_at": meta["created_at"]})
    return meta


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _copy_verified(src: Path, dst: Path) -> str:
    """Copies src to dst through a .partial file, hashing the source as it is
    read, then re-reads the copy and only renames it into place if the two
    hashes match. Returns the sha256."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    partial = dst.with_name(dst.name + ".partial")
    digest = hashlib.sha256()
    try:
        with src.open("rb") as fin, partial.open("wb") as fout:
            for chunk in iter(lambda: fin.read(1 << 20), b""):
                digest.update(chunk)
                fout.write(chunk)
        if _file_sha256(partial) != digest.hexdigest():
            raise BackupError(f"copy of {src.name} did not match the original")
        os.replace(partial, dst)
    finally:
        partial.unlink(missing_ok=True)
    return digest.hexdigest()


def _read_media_manifest(manifest_path: Path) -> dict[str, dict]:
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    files = data.get("files") if isinstance(data, dict) else None
    return {f["path"]: f for f in files if isinstance(f, dict) and "path" in f} if isinstance(files, list) else {}


def run_media_sync(referenced: list[str]) -> dict:
    """Incrementally mirrors the uploads that notes and diagrams reference into
    /backups/media, keeping the same relative layout so a restore is a plain
    copy back. Only manual: the first run is several GB.

    A file is skipped when the manifest already lists it at the same size and
    the copy is still there -- uploads are written once under unique names, so
    that is a cheap and reliable "unchanged". Everything else is copied and
    verified. Files that are no longer referenced (a deleted note) are left in
    the backup: a backup that quietly forgets things is not much of one.
    """
    _require_dir()
    started = time.monotonic()
    uploads = Path(app_config.upload_dir)
    if not uploads.is_dir():
        raise BackupError(f"Uploads folder {uploads} is not mounted")
    dest = BACKUPS_DIR / MEDIA_DIR_NAME
    manifest_path = dest / MEDIA_MANIFEST
    manifest = _read_media_manifest(manifest_path)
    copied = unchanged = 0
    copied_bytes = 0
    missing: list[str] = []

    try:
        for rel in sorted(set(referenced)):
            try:
                src = resolve_within(uploads, rel)
                dst = resolve_within(dest, rel)
            except ValueError:
                missing.append(rel)
                continue
            if not src.is_file():
                missing.append(rel)
                continue
            size = src.stat().st_size
            entry = manifest.get(rel)
            if entry and entry.get("size_bytes") == size and dst.is_file() and dst.stat().st_size == size:
                unchanged += 1
                continue
            manifest[rel] = {"path": rel, "size_bytes": size, "sha256": _copy_verified(src, dst)}
            copied += 1
            copied_bytes += size
    except Exception as exc:
        _write_status("media", {"status": "failed", "error": str(exc), "source": "manual",
                                "last_run_at": _now().isoformat()})
        raise
    finally:
        # Written even after a failure so files already copied are not redone.
        if manifest:
            dest.mkdir(parents=True, exist_ok=True)
            entries = [manifest[k] for k in sorted(manifest)]
            payload = {"updated_at": _now().isoformat(), "file_count": len(entries),
                       "total_bytes": sum(e["size_bytes"] for e in entries), "files": entries}
            tmp = manifest_path.with_name(manifest_path.name + ".partial")
            tmp.write_text(json.dumps(payload, indent=1), encoding="utf-8")
            os.replace(tmp, manifest_path)

    result = {
        "copied": copied, "unchanged": unchanged, "missing": missing[:20], "missing_count": len(missing),
        "copied_bytes": copied_bytes, "total_files": len(manifest),
        "total_bytes": sum(e["size_bytes"] for e in manifest.values()),
        "duration_seconds": round(time.monotonic() - started, 1),
    }
    _write_status("media", {"status": "ok", "error": None, "source": "manual", **result,
                            "last_run_at": _now().isoformat(), "last_success_at": _now().isoformat()})
    return result


def list_backups() -> dict:
    """What the Settings page shows: every database dump we track, newest
    first, plus how the last run of each kind went."""
    if not BACKUPS_DIR.is_dir():
        return {"mounted": False, "directory": str(BACKUPS_DIR), "backups": [], "status": {}}
    backups = [{**meta, "size_bytes": archive.stat().st_size} for archive, meta in _tracked("db")]
    backups.sort(key=lambda meta: meta.get("created_at", ""), reverse=True)
    return {
        "mounted": True,
        "directory": str(BACKUPS_DIR),
        "backups": backups,
        "status": {kind: _read_status(kind) for kind in STATUS_FILES},
    }

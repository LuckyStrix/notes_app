import shutil
import uuid
from pathlib import Path

from app.config import settings


def delete_note_storage(note_id: uuid.UUID) -> None:
    """Removes a note's upload directory (its media file, if any) from disk.
    DB rows (note_files, transcripts) are already gone via ON DELETE CASCADE
    by the time this is called -- this just prevents the underlying files
    from being orphaned on disk forever. Safe to call for a note that never
    had a file uploaded.
    """
    note_dir = Path(settings.upload_dir) / str(note_id)
    shutil.rmtree(note_dir, ignore_errors=True)


def sanitize_filename(filename: str | None) -> str:
    """Reduces a client-supplied filename to a bare, path-free basename, so it
    can't be used to escape the note's upload directory -- e.g. a filename of
    "../../etc/passwd" or an absolute path. Falls back to "upload" for a name
    that sanitizes away to nothing (empty, ".", "..").
    """
    name = Path(filename or "").name
    if not name or name in (".", ".."):
        return "upload"
    return name


def resolve_within(base: Path, relative: str) -> Path:
    """Joins `relative` onto `base` and raises ValueError if the result would
    escape `base`. Defense in depth for paths read back out of the database,
    on top of sanitize_filename() guarding what gets written in the first
    place.
    """
    base = base.resolve()
    candidate = (base / relative).resolve()
    if candidate != base and base not in candidate.parents:
        raise ValueError(f"path escapes base directory: {relative!r}")
    return candidate

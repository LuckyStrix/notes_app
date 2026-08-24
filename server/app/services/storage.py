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

import uuid

import pytest

from app.config import settings
from app.services.storage import delete_note_storage, resolve_within, sanitize_filename


def test_delete_note_storage_removes_existing_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path))
    note_id = uuid.uuid4()
    note_dir = tmp_path / str(note_id)
    note_dir.mkdir()
    (note_dir / "recording.wav").write_bytes(b"fake audio")

    delete_note_storage(note_id)

    assert not note_dir.exists()


def test_delete_note_storage_tolerates_missing_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path))

    delete_note_storage(uuid.uuid4())  # should not raise


def test_sanitize_filename_keeps_a_plain_name():
    assert sanitize_filename("recording.wav") == "recording.wav"


def test_sanitize_filename_strips_relative_traversal():
    assert sanitize_filename("../../etc/passwd") == "passwd"


def test_sanitize_filename_strips_absolute_paths():
    assert sanitize_filename("/etc/passwd") == "passwd"


def test_sanitize_filename_falls_back_when_nothing_survives():
    assert sanitize_filename("..") == "upload"
    assert sanitize_filename(".") == "upload"
    assert sanitize_filename("") == "upload"
    assert sanitize_filename(None) == "upload"


def test_resolve_within_allows_a_path_inside_base(tmp_path):
    resolved = resolve_within(tmp_path, "notes/note-1/file.wav")
    assert resolved == (tmp_path / "notes" / "note-1" / "file.wav").resolve()


def test_resolve_within_rejects_a_relative_escape(tmp_path):
    with pytest.raises(ValueError):
        resolve_within(tmp_path, "../outside")


def test_resolve_within_rejects_a_dotdot_escape_buried_in_the_path(tmp_path):
    with pytest.raises(ValueError):
        resolve_within(tmp_path, "note-1/../../outside")

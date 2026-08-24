import uuid

from app.config import settings
from app.services.storage import delete_note_storage


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

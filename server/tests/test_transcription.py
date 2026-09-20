import inspect

import pytest
from pydantic import ValidationError

from app.schemas.settings import SettingsUpdate
from app.services.transcription import resolve_language


def test_language_is_passed_through_as_an_iso_code():
    assert resolve_language("en") == "en"
    assert resolve_language("  EN ") == "en"
    assert resolve_language("fil") == "fil"  # 3-letter codes exist too


def test_auto_and_blank_mean_let_whisper_detect():
    assert resolve_language("auto") is None
    assert resolve_language("") is None
    assert resolve_language(None) is None


def test_garbage_language_is_refused_not_passed_to_whisper():
    for bad in ("english", "e", "en-US", "../../x", "e1"):
        with pytest.raises(ValueError):
            resolve_language(bad)


def test_settings_api_only_accepts_valid_language_values():
    assert SettingsUpdate(whisper_language="en").whisper_language == "en"
    assert SettingsUpdate(whisper_language="auto").whisper_language == "auto"
    assert SettingsUpdate().whisper_language is None  # omitted = unchanged
    for bad in ("English", "EN", "", "en-US", "x"):
        with pytest.raises(ValidationError):
            SettingsUpdate(whisper_language=bad)


def test_uploading_a_recording_does_not_start_transcription():
    """Transcription is a manual action: upload_media must not enqueue it."""
    from app.api import media

    upload_source = inspect.getsource(media.upload_media)
    assert "transcribe_note" not in upload_source
    assert "extract_document_text" in upload_source  # documents still extract immediately
    assert "transcribe_note" in inspect.getsource(media.start_transcription)


def test_whisper_is_always_given_an_explicit_language_argument():
    from app.jobs import transcribe

    assert "language=resolve_language(language)" in inspect.getsource(transcribe._run_whisper)

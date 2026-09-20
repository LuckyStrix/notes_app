"""Pure helpers for transcription settings (no DB / GPU imports, so they are unit-testable).

Why the language is a setting instead of being left to Whisper: with no `language`
argument, faster-whisper guesses from the first 30 seconds of audio. Recordings that
open with silence, room noise or small talk get mislabelled -- English lectures came
back as Welsh ("cy") and were then transcribed as Welsh-looking gibberish. Forcing
the language avoids that entirely.
"""
import re

AUTO = "auto"
_ISO_CODE = re.compile(r"^[a-z]{2,3}$")

# Same rule the API enforces on input (schemas.settings.SettingsUpdate) and the
# database enforces with a CHECK constraint.
LANGUAGE_PATTERN = r"^(auto|[a-z]{2,3})$"


def resolve_language(setting: str | None) -> str | None:
    """The value to pass as faster-whisper's `language`: an ISO 639 code such as
    "en", or None to let Whisper auto-detect (setting "auto")."""
    if setting is None:
        return None
    value = setting.strip().lower()
    if value in ("", AUTO):
        return None
    if not _ISO_CODE.match(value):
        raise ValueError(f"Invalid transcription language {setting!r}: use a 2-3 letter code like 'en', or 'auto'")
    return value

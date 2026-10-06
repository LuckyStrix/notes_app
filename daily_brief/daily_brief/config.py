"""Defaults, environment, and parsing of the 'Brief Settings' note."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

BRIEF_PROJECT = "Brief"
BRIEFS_GROUP = "Briefs"
NOTE_INSTRUCTIONS = "Brief Instructions"
NOTE_SETTINGS = "Brief Settings"
NOTE_CONTROL = "Brief Control"
NOTE_STATUS = "Brief Status"
CONTROL_NOTES = (NOTE_INSTRUCTIONS, NOTE_SETTINGS, NOTE_CONTROL, NOTE_STATUS)

WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


@dataclass(frozen=True)
class Env:
    """Deployment config: where things are and the secrets. Never from a note."""

    data_dir: Path
    notes_api_url: str
    router_url: str
    router_api_key: str
    github_token: str

    @classmethod
    def from_environ(cls, environ=os.environ) -> "Env":
        return cls(
            data_dir=Path(environ.get("DB_DATA_DIR", "data")),
            notes_api_url=environ.get("DB_NOTES_API_URL", "http://localhost:8000").rstrip("/"),
            router_url=environ.get("DB_ROUTER_URL", "http://localhost:20128/v1").rstrip("/"),
            router_api_key=environ.get("DB_ROUTER_API_KEY", ""),
            github_token=environ.get("GITHUB_TOKEN", ""),
        )


@dataclass(frozen=True)
class Settings:
    """Everything editable from the 'Brief Settings' note. Bad values fall back to
    these defaults (with a warning in Brief Status) rather than stopping the brief."""

    run_time: str = "06:00"
    timezone: str = "America/New_York"
    lookahead_days: int = 14
    weekly_day: str = "monday"
    drafters: tuple[str, ...] = ()
    editor: str = ""
    github_owner: str = "LuckyStrix"
    github_active_days: int = 30
    note_projects: tuple[str, ...] = ()
    note_project_days: int = 14
    calendars: tuple[str, ...] = ("primary",)


_LIST_KEYS = {"drafters", "note_projects", "calendars"}
_INT_KEYS = {"lookahead_days": (1, 60), "github_active_days": (1, 365), "note_project_days": (1, 90)}
_KNOWN = _LIST_KEYS | set(_INT_KEYS) | {"editor", "github_owner", "run_time", "timezone", "weekly_day"}

# "- `key`: value" is fine: notes are Markdown, so people add bullets and backticks.
_LINE = re.compile(r"^\s*(?:[-*+]\s+)?[`*_]*([A-Za-z][A-Za-z0-9_]*)[`*_]*\s*:\s*(.*?)\s*$")


def _clean(value: str) -> str:
    return value.strip().strip("`*_").strip()


def parse_settings(text: str) -> tuple[Settings, list[str]]:
    """Returns (settings, warnings). Pure. Parsing stops at the first '## ' heading,
    so the explanatory section below the settings (which itself contains 'key: text'
    lines) is never read as values. Last occurrence of a key wins."""
    raw: dict[str, str] = {}
    warnings: list[str] = []
    for line in text.splitlines():
        if line.startswith("## "):
            break
        m = _LINE.match(line)
        if not m:
            continue
        key, value = m.group(1).lower(), _clean(m.group(2))
        if key in _KNOWN:
            raw[key] = value
        elif "_" in key:
            # Prose like "Note: ..." has no underscore; a snake_case key is a typo.
            warnings.append(f"unknown setting '{key}' ignored")

    defaults, values = Settings(), {}
    for key, value in raw.items():
        if key in _LIST_KEYS:
            items = tuple(i for i in (_clean(p) for p in re.split(r"[,;]", value)) if i)
            if key == "calendars" and not items:
                continue
            values[key] = items
        elif key in _INT_KEYS:
            lo, hi = _INT_KEYS[key]
            try:
                n = int(value)
            except ValueError:
                n = lo - 1
            if lo <= n <= hi:
                values[key] = n
            else:
                warnings.append(f"{key}: expected a whole number {lo}-{hi}, got '{value}'; using {getattr(defaults, key)}")
        elif key == "run_time":
            if re.fullmatch(r"([01]?\d|2[0-3]):[0-5]\d", value):
                h, m = value.split(":")
                values[key] = f"{int(h):02d}:{m}"
            else:
                warnings.append(f"run_time: expected HH:MM (24-hour), got '{value}'; using {defaults.run_time}")
        elif key == "timezone":
            try:
                ZoneInfo(value)
                values[key] = value
            except (ZoneInfoNotFoundError, ValueError):
                warnings.append(f"timezone: unknown zone '{value}'; using {defaults.timezone}")
        elif key == "weekly_day":
            if value.lower() in WEEKDAYS:
                values[key] = value.lower()
            else:
                warnings.append(f"weekly_day: expected a weekday name, got '{value}'; using {defaults.weekly_day}")
        else:
            values[key] = value
    return Settings(**{**defaults.__dict__, **values}), warnings


DEFAULT_SETTINGS_NOTE = """\
# Brief Settings

One `key: value` line per setting. Saved changes apply on the next run. Lists are comma-separated.
A bad value is ignored (the default is used) and the problem is shown in Brief Status.

run_time: 06:00
timezone: America/New_York
weekly_day: monday
lookahead_days: 14

drafters:
editor:

github_owner: LuckyStrix
github_active_days: 30

note_projects:
note_project_days: 14
calendars: primary

## What these mean

(Everything below this heading is ignored by the parser.)

- drafters: 2-3 model ids from your 9router dashboard (e.g. kr/claude-sonnet-4.5). Each writes its own draft.
  Pick different models: the point is that they disagree sometimes.
- editor: the model that reads all drafts against the facts and writes the final. Use your best one.
  While drafters or editor is empty you get the brief without the AI sections.
- weekly_day: the day the brief also gives a short outlook for the week.
- note_projects: the ONLY notes-app projects the brief may read, by name. Leave empty to read none.
  The Brief project itself is always readable. GitHub repos need no list: every repo you own
  that was pushed to in the last github_active_days days counts.
- calendars: Google Calendar ids to include (primary is your main one).
"""

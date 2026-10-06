"""The Brief project's control notes: Instructions, Settings, Control, Status.

You steer the brief by editing notes, so this is the whole "UI". Instructions, Settings and
Control are yours; Status is written only by the job. Every write to a note makes the notes
app re-embed it, so `update_if_changed` exists to keep Status from churning the GPU.
"""
from __future__ import annotations

import re

from .config import (CONTROL_NOTES, DEFAULT_SETTINGS_NOTE, NOTE_CONTROL, NOTE_INSTRUCTIONS,
                     NOTE_SETTINGS, NOTE_STATUS)

DEFAULT_INSTRUCTIONS_NOTE = """\
# Brief Instructions

These are read on every run. Edit freely; the sections are matched by their headings. Models never see your other notes, only what the job gathers (see the README).

## About me

(Who you are and what a good day looks like. Goes to every model. Example topics: your classes or job, what you are working toward, what you want protected time for.)

## Drafter

Write for someone who reads this at 6am on a phone. Lead with what is time-sensitive today. Prefer a short, specific list over general advice.

## Editor

Keep it short. If drafts disagree about what matters most, choose what the deadlines and the calendar support. Remove anything generic.
"""

_COMMAND_HELP = """\
# Brief Control

Type `run` (write today's brief now) or `dry run` (preview it below, save nothing) on a line of its own, then save. It is picked up within a minute and this note is rewritten with the result.

---
"""

DEFAULTS = {NOTE_INSTRUCTIONS: DEFAULT_INSTRUCTIONS_NOTE, NOTE_SETTINGS: DEFAULT_SETTINGS_NOTE,
            NOTE_CONTROL: _COMMAND_HELP, NOTE_STATUS: "# Brief Status\n\nNo run yet.\n"}

_COMMAND = re.compile(r"^\s*(run(?: now)?|dry[ -]run)\s*$", re.I)
_SECTIONS = {"about me": "about", "drafter": "drafter", "editor": "editor"}


def parse_instructions(text: str) -> dict[str, str]:
    """Maps 'about' / 'drafter' / 'editor' to the text under the matching '## ' heading."""
    out: dict[str, str] = {}
    current = None
    for line in text.splitlines():
        if line.startswith("## "):
            current = _SECTIONS.get(line[3:].strip().lower())
            if current:
                out[current] = ""
            continue
        if current:
            out[current] += line + "\n"
    return {k: v.strip() for k, v in out.items()}


def parse_command(text: str) -> str | None:
    """'run' or 'dry-run' if a command line appears before the first '---' rule."""
    for line in text.splitlines():
        if line.strip() == "---":
            break
        m = _COMMAND.match(line)
        if m:
            return "dry-run" if m.group(1).lower().startswith("dry") else "run"
    return None


def control_result(text: str) -> str:
    return _COMMAND_HELP + "\n" + text.strip() + "\n"


def ensure_control_notes(api) -> dict[str, dict]:
    """Creates any missing control note (with its default text); returns {title: note}."""
    group = api.ensure_group()
    by_title: dict[str, dict] = {}
    for n in api.brief_notes():
        by_title.setdefault(n["title"], n)
    for title in CONTROL_NOTES:
        if title not in by_title:
            by_title[title] = api.create_note(title, DEFAULTS[title], group["id"])
    return by_title


def update_if_changed(api, note: dict, body: str) -> dict:
    if (note.get("body") or "").strip() == body.strip():
        return note
    return api.update_note(note["id"], body)

"""Daily loop with catch-up when the PC was off at the scheduled time.

State is a small JSON file in the data dir (not in the notes): which date was last
attempted, how often, and whether it was incomplete. A brief that came out incomplete
(Google down, token expired) is retried every 30 minutes, up to MAX_ATTEMPTS a day, by
updating the same dated note in place.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import Env, NOTE_CONTROL, NOTE_INSTRUCTIONS, NOTE_SETTINGS, NOTE_STATUS, Settings, parse_settings
from .control import control_result, ensure_control_notes, parse_command, update_if_changed
from .notes_api import NotesApi, NotesApiError
from .panel import Router
from .pipeline import run_brief, status_text

POLL_SECONDS = 60
RETRY_AFTER = timedelta(minutes=30)
MAX_ATTEMPTS = 4


@dataclass
class State:
    date: str = ""
    attempts: int = 0
    degraded: bool = False
    last_attempt: str = ""

    @classmethod
    def load(cls, path: Path) -> "State":
        try:
            return cls(**json.loads(path.read_text()))
        except (OSError, ValueError, TypeError):
            return cls()

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.__dict__))
        tmp.replace(path)  # atomic: a crash mid-write must not lose the day's attempt count


def is_due(now: datetime, run_time: str, state: State) -> bool:
    """Pure. Due once `run_time` has passed today and today has not been attempted; an
    incomplete attempt is retried after RETRY_AFTER, MAX_ATTEMPTS times at most."""
    h, m = map(int, run_time.split(":"))
    if now < now.replace(hour=h, minute=m, second=0, microsecond=0):
        return False
    if state.date != now.date().isoformat():
        return True
    if state.degraded and state.attempts < MAX_ATTEMPTS and state.last_attempt:
        return now - datetime.fromisoformat(state.last_attempt) >= RETRY_AFTER
    return False


class Scheduler:
    def __init__(self, env: Env, api: NotesApi, router: Router, log=print):
        self.env, self.api, self.router, self.log = env, api, router, log
        self.state_path = env.data_dir / "state.json"
        self.heartbeat_path = env.data_dir / "heartbeat"
        self.last_result = None
        self._notes: dict[str, dict] = {}
        self._notes_at = 0.0

    def _control_notes(self) -> dict[str, dict]:
        """Control-note ids, refreshed hourly. Listing the Brief project returns every dated
        brief's full body (one more per day), so it is not done on every poll."""
        if not self._notes or time.monotonic() - self._notes_at > 3600:
            self.api.ensure_brief_project()
            self._notes = ensure_control_notes(self.api)
            self._notes_at = time.monotonic()
        return self._notes

    def tick(self, now: datetime | None = None) -> None:
        notes = self._control_notes()
        settings, warnings = parse_settings(self.api.note(notes[NOTE_SETTINGS]["id"])["body"] or "")
        now = (now or datetime.now(ZoneInfo(settings.timezone))).astimezone(ZoneInfo(settings.timezone))
        control = self.api.note(notes[NOTE_CONTROL]["id"])
        command = parse_command(control["body"] or "")
        state = State.load(self.state_path)

        if command:
            self.log(f"command from Brief Control: {command}")
            # Clear the command first: if anything below fails, it must not re-run every poll.
            self.api.update_note(control["id"], control_result("Running…"))
            self._run(notes, settings, warnings, now, dry_run=(command == "dry-run"), control=control, state=None)
        elif is_due(now, settings.run_time, state):
            self.log(f"scheduled run for {now.date()}")
            self._run(notes, settings, warnings, now, dry_run=False, control=None, state=state)

    def _run(self, notes, settings: Settings, warnings, now, dry_run, control, state: State | None) -> None:
        if state is not None:  # count the attempt first: a crash must not loop forever
            if state.date != now.date().isoformat():
                state.date, state.attempts = now.date().isoformat(), 0
            state.attempts += 1
            state.last_attempt = now.isoformat()
            state.degraded = True
            state.save(self.state_path)
        instructions = self.api.note(notes[NOTE_INSTRUCTIONS]["id"])["body"] or ""
        result = run_brief(self.env, settings, warnings, self.api, self.router, instructions, now, dry_run)
        self.last_result = result
        if state is not None:
            state.degraded = result.degraded
            state.save(self.state_path)
        if control is not None:
            text = result.body if dry_run else f"Saved **{result.title}** at {now:%H:%M}."
            if result.degraded:
                text += "\n\n⚠ Incomplete: see Brief Status."
            self.api.update_note(control["id"], control_result(text))
        update_if_changed(self.api, notes[NOTE_STATUS], status_text(result, now, settings, warnings))

    def serve(self) -> None:
        self.log("daily_brief started")
        while True:
            try:
                self.tick()
            except NotesApiError as exc:
                self.log(f"notes app unreachable: {exc}")  # retried next poll; nothing to record it in
            except Exception as exc:  # one bad run must not stop tomorrow's
                self.log(f"run failed: {type(exc).__name__}: {exc}")
            self.heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
            self.heartbeat_path.write_text(str(time.time()))
            time.sleep(POLL_SECONDS)

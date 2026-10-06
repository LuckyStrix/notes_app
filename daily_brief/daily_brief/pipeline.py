"""One brief, end to end: gather -> facts -> panel -> render -> dated note."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from . import github, google
from .config import Env, Settings
from .control import parse_instructions
from .gather import build_facts, note_project_facts
from .notes_api import NotesApi, NotesApiError
from .panel import PanelResult, Router, run_panel
from .render import long_date, render_brief


@dataclass
class RunResult:
    title: str
    body: str
    panel: PanelResult
    source_errors: list[str]
    saved: bool = False
    warnings: list[str] = field(default_factory=list)

    @property
    def degraded(self) -> bool:
        """A source failed, so the brief is incomplete and worth retrying later today."""
        return bool(self.source_errors)


def run_brief(env: Env, settings: Settings, warnings: list[str], api: NotesApi, router: Router,
              instructions_text: str, now: datetime | None = None, dry_run: bool = False) -> RunResult:
    tz = ZoneInfo(settings.timezone)
    now = (now or datetime.now(tz)).astimezone(tz)
    today = now.date()
    errors: list[str] = []

    events, tasks = [], []
    try:
        events, tasks, g_warnings = google.fetch(env.data_dir / "google_token.json", tz, settings.calendars,
                                                 today, today + timedelta(days=settings.lookahead_days))
        errors += g_warnings
    except google.GoogleError as exc:
        errors.append(f"Google Calendar and Tasks unavailable: {exc}")

    repos = []
    try:
        repos = github.fetch(settings.github_owner, env.github_token, now, settings.github_active_days)
    except github.GitHubError as exc:
        errors.append(f"GitHub unavailable: {exc}")

    projects = []
    try:
        projects, w = note_project_facts(api, settings, now)
        errors += w
    except NotesApiError as exc:
        errors.append(f"Notes projects unavailable: {exc}")

    facts = build_facts(now, settings, events, tasks, repos, projects, errors)
    panel = run_panel(facts, settings.drafters, settings.editor, parse_instructions(instructions_text), router)
    body = render_brief(facts, panel.ai, panel.notes)
    result = RunResult(f"Daily Brief {today.isoformat()}", body, panel, errors, warnings=warnings)

    if not dry_run:
        existing = {n["title"]: n for n in api.brief_notes()}
        note = existing.get(result.title)
        if note:
            api.update_note(note["id"], body)
        else:
            api.create_note(result.title, body, api.ensure_group()["id"])
        result.saved = True
    return result


def status_text(result: RunResult | None, now: datetime, settings: Settings, warnings: list[str]) -> str:
    lines = ["# Brief Status", "", "Written by the job; edits here are overwritten.", ""]
    if result is None:
        lines.append("No run yet.")
    else:
        p = result.panel
        lines += [f"**Last run:** {now:%Y-%m-%d %H:%M} ({settings.timezone}) — "
                  + ("saved" if result.saved else "dry run, not saved")
                  + (", **incomplete** (see below)" if result.degraded else ""), "", "### Models"]
        if not p.drafts:
            lines.append("- No models were called.")
        for d in p.drafts:
            lines.append(f"- drafter `{d.model}`: " + ("ok" if d.ok else f"FAILED — {d.error[:160]}"))
        if p.editor_model and p.drafts:
            lines.append(f"- editor `{p.editor_model}`: " + ("ok" if p.editor_ok else f"FAILED — {p.editor_error[:160]}"))
        if p.removed:
            lines += ["", "### Lines removed by checks"] + [f"- {r}" for r in p.removed]
        if result.source_errors:
            lines += ["", "### Data problems"] + [f"- {e}" for e in result.source_errors]
    if warnings:
        lines += ["", "### Settings problems"] + [f"- {w}" for w in warnings]
    return "\n".join(lines) + "\n"

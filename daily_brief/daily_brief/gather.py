"""Builds the facts blob the brief is made from.

`build_facts` is pure (normalised inputs in, one dict out). `note_project_facts` is the one
impure helper: it reads the allowlisted notes-app projects through the GET-only side of
NotesApi.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta

from .config import BRIEF_PROJECT, Settings
from .render import week_end

_SNIPPET = 300
_MAX_NOTES = 8


def _snippet(note: dict) -> str:
    text = (note.get("summary") or note.get("body") or "").strip()
    return re.sub(r"\s+", " ", text)[:_SNIPPET]


def note_project_facts(api, settings: Settings, now: datetime) -> tuple[list[dict], list[str]]:
    """Allowlisted projects only, matched by name (case-insensitive). Returns (facts, warnings)."""
    wanted = {n.lower(): n for n in settings.note_projects if n.lower() != BRIEF_PROJECT.lower()}
    if not wanted:
        return [], []
    by_name = {p["name"].lower(): p for p in api.projects()}
    cutoff = now - timedelta(days=settings.note_project_days)
    facts, warnings = [], []
    for key, label in wanted.items():
        project = by_name.get(key)
        if not project:
            warnings.append(f"note_projects: no notes-app project named '{label}'")
            continue
        recent = []
        for n in api.notes(project["id"]):
            updated = datetime.fromisoformat(n["updated_at"].replace("Z", "+00:00"))
            if updated >= cutoff:
                recent.append({"title": n["title"], "updated": updated.astimezone(now.tzinfo).date().isoformat(),
                               "snippet": _snippet(n)})
        recent.sort(key=lambda r: r["updated"], reverse=True)
        facts.append({"name": project["name"], "description": (project.get("description") or "")[:200],
                      "recent_notes": recent[:_MAX_NOTES]})
    return facts, warnings


def _is_class(e: dict, keywords: tuple[str, ...]) -> bool:
    hay = f"{e.get('title', '')} {e.get('calendar', '')}".lower()
    return any(k.lower() in hay for k in keywords if k.strip())


def build_facts(now: datetime, settings: Settings, events: list[dict], tasks: list[dict],
                repos: list[dict], projects: list[dict], source_errors: list[str]) -> dict:
    """Everything the brief states, in one dict. Projects get small 1-based ids: models copy
    '3' back far more reliably than a name, and the guard maps ids back to names."""
    today = now.date()
    events = [{**e, "irregular": False} if e.get("irregular") and _is_class(e, settings.class_keywords) else e
              for e in events]
    items = []
    for i, p in enumerate([*repos, *projects], start=1):
        items.append({"id": i, "kind": "repo" if "pushed" in p else "notes_project", **p})
    return {
        "today": today.isoformat(),
        "weekday": today.strftime("%A"),
        "is_weekly": today.strftime("%A").lower() == settings.weekly_day,
        "week_end": week_end(today).isoformat(),
        "timezone": settings.timezone,
        "lookahead_days": settings.lookahead_days,
        # Tag events with their calendar only when there is more than one to tell apart.
        "multi_calendar": len({e.get("calendar") for e in events}) > 1,
        "events": sorted(events, key=lambda e: (e["date"], e["start_time"] or "")),
        "tasks": sorted(tasks, key=lambda t: (t["due"] or "9999", t["title"].lower())),
        "projects": items,
        "source_errors": source_errors,
    }

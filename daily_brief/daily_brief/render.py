"""Deterministic brief sections: events, tasks, week view (pure).

Everything factual (what is when, what is due) is rendered here from the facts, never by a
model, so a weak model cannot drop or invent an event. Models only add prose around it.
"""
from __future__ import annotations

from datetime import date, timedelta

NO_DATE_LIMIT = 8


def _d(s: str) -> date:
    return date.fromisoformat(s)


def short_date(d: date) -> str:
    # No %-d: it is glibc-only and this should not care what OS builds it.
    return f"{d:%a %b} {d.day}"


def long_date(d: date) -> str:
    return f"{d:%A, %B} {d.day}, {d.year}"


def events_on(events: list[dict], day: date) -> list[dict]:
    return [e for e in events if _d(e["date"]) <= day <= _d(e.get("until") or e["date"])]


def fmt_event(e: dict, day: date) -> str:
    when = f"{e['start_time']}–{e['end_time']}" if e["start_time"] else "all day"
    line = f"- **{when}** {e['title']}"
    if e["location"]:
        line += f" ({e['location']})"
    if e.get("until"):
        line += f" — through {short_date(_d(e['until']))}"
    return line


def fmt_task(t: dict, today: date) -> str:
    line = f"- [ ] {t['title']}"
    if t["due"] and _d(t["due"]) < today:
        line += f" — overdue since {short_date(_d(t['due']))}"
    if t["list"]:
        line += f" _({t['list']})_"
    return line


def _day_block(facts: dict, day: date, today: date, with_heading: bool) -> list[str]:
    ev = events_on(facts["events"], day)
    tasks = [t for t in facts["tasks"] if t["due"] and _d(t["due"]) == day]
    if not ev and not tasks:
        return []
    lines = [f"**{short_date(day)}**"] if with_heading else []
    lines += [fmt_event(e, day) for e in ev] + [fmt_task(t, today) for t in tasks]
    return lines + [""]


def render_today(facts: dict) -> list[str]:
    today = _d(facts["today"])
    ev = events_on(facts["events"], today)
    tasks = [t for t in facts["tasks"] if t["due"] and _d(t["due"]) <= today]  # overdue first (sorted)
    if not ev and not tasks:
        return ["Nothing scheduled and nothing due.", ""]
    return [fmt_event(e, today) for e in ev] + [fmt_task(t, today) for t in tasks] + [""]


def week_end(today: date) -> date:
    return today + timedelta(days=6 - today.weekday())  # Sunday


def render_rest_of_week(facts: dict) -> list[str]:
    today = _d(facts["today"])
    out: list[str] = []
    day = today + timedelta(days=1)
    while day <= week_end(today):
        out += _day_block(facts, day, today, True)
        day += timedelta(days=1)
    return out or ["Nothing else this week.", ""]


def render_upcoming(facts: dict) -> list[str]:
    today = _d(facts["today"])
    last = today + timedelta(days=facts["lookahead_days"])
    out: list[str] = []
    day = week_end(today) + timedelta(days=1)
    while day <= last:
        out += _day_block(facts, day, today, True)
        day += timedelta(days=1)
    undated = [t for t in facts["tasks"] if not t["due"]]
    if undated:
        out += ["**No due date**"] + [fmt_task(t, today) for t in undated[:NO_DATE_LIMIT]]
        if len(undated) > NO_DATE_LIMIT:
            out.append(f"- …and {len(undated) - NO_DATE_LIMIT} more")
        out.append("")
    return out or [f"Nothing in the next {facts['lookahead_days']} days.", ""]


def _project_fallback(p: dict) -> str:
    if p["kind"] == "repo":
        if p["private"]:
            return "private repo"
        return p["commits"][0] if p.get("commits") else (p.get("description") or "no recent commit messages")
    notes = p.get("recent_notes") or []
    return f"{len(notes)} recently updated note(s)" if notes else "no recent note activity"


def render_projects(facts: dict, summaries: dict[int, str]) -> list[str]:
    """Every project appears, whether or not a model summarised it."""
    if not facts["projects"]:
        return ["No active repos or allowlisted projects.", ""]
    out = []
    for p in facts["projects"]:
        detail = f" — last push {short_date(_d(p['pushed']))}" if p["kind"] == "repo" else ""
        out.append(f"- **{p['name']}**{detail}: {summaries.get(p['id']) or _project_fallback(p)}")
    return out + [""]


def render_brief(facts: dict, ai: dict | None, footer: list[str]) -> str:
    """The note body. `ai` is guard-checked: {"focus": [...], "outlook": str,
    "projects": {id: summary}, "watchouts": [...]} or None when no model produced anything."""
    ai = ai or {}
    lines: list[str] = []
    for err in facts["source_errors"]:
        lines.append(f"> ⚠ {err}")
    if facts["source_errors"]:
        lines.append("")
    if ai.get("focus"):
        lines += ["## Focus", ""] + [f"- {f}" for f in ai["focus"]] + [""]
    if ai.get("outlook"):
        lines += ["## Week outlook", "", ai["outlook"], ""]
    lines += ["## Today", ""] + render_today(facts)
    lines += ["## Rest of this week", ""] + render_rest_of_week(facts)
    lines += [f"## Upcoming ({facts['lookahead_days']} days)", ""] + render_upcoming(facts)
    lines += ["## Active projects", ""] + render_projects(facts, ai.get("projects", {}))
    if ai.get("watchouts"):
        lines += ["## Watch-outs", ""] + [f"- {w}" for w in ai["watchouts"]] + [""]
    if footer:
        lines += ["---", ""] + [f"_{f}_" for f in footer]
    return "\n".join(lines).rstrip() + "\n"

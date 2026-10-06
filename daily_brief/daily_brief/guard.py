"""Code checks on AI output: nothing not in the facts survives (pure).

Prompting asks models to stick to the facts; this enforces the part that can be checked
mechanically. Every date or time a model writes must appear in the facts, private repos
never get a model-written summary, and project ids must exist. Lines that fail are dropped
and counted, and the count is shown in the brief's footer so an override is never silent.
"""
from __future__ import annotations

import json
import re
from datetime import date

from .render import events_on, irregular_events

MAX_LEN = 400
MAX_FOCUS = 5
MAX_WATCHOUTS = 4

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}


class BadOutput(Exception):
    """The model answered, but not with usable JSON of the right shape."""


# ---- JSON extraction -------------------------------------------------------------------
def extract_json(raw: str) -> dict:
    """First top-level {...} object in the text. Tolerates ```json fences and chatter."""
    text = re.sub(r"```(?:json)?", "", raw)
    start = text.find("{")
    if start < 0:
        raise BadOutput("no JSON object in the answer")
    depth, in_str, esc = 0, False, False
    for i in range(start, len(text)):
        c = text[i]
        if in_str:
            esc = (c == "\\") and not esc
            if c == '"' and not esc:
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                try:
                    obj = json.loads(text[start:i + 1])
                except json.JSONDecodeError as exc:
                    raise BadOutput(f"invalid JSON: {exc}") from exc
                if not isinstance(obj, dict):
                    raise BadOutput("JSON is not an object")
                return obj
    raise BadOutput("JSON object is not closed (answer cut off?)")


def validate_draft(obj: dict) -> dict:
    """Shape check + coercion to {reasoning, focus, outlook, projects, watchouts}.
    Missing optional fields default to empty; wrong types raise BadOutput so the caller can
    retry with the error. No length limits here: a long-winded answer is clipped later, not
    rejected (rejecting costs a whole drafter)."""
    def str_list(key):
        v = obj.get(key, [])
        if isinstance(v, str):
            v = [v]
        if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
            raise BadOutput(f"'{key}' must be a list of strings")
        return v

    projects = obj.get("projects", [])
    if not isinstance(projects, list):
        raise BadOutput("'projects' must be a list of {id, summary}")
    clean_projects = []
    for p in projects:
        if not isinstance(p, dict) or not isinstance(p.get("summary"), str):
            raise BadOutput("each project needs an integer 'id' and a string 'summary'")
        try:
            clean_projects.append({"id": int(p["id"]), "summary": p["summary"]})
        except (KeyError, TypeError, ValueError):
            raise BadOutput("each project needs an integer 'id' and a string 'summary'") from None
    outlook = obj.get("outlook", "")
    if not isinstance(outlook, str):
        raise BadOutput("'outlook' must be a string")
    if "focus" not in obj:
        raise BadOutput("missing 'focus'")
    summaries = {}
    for key in ("day_summary", "irregular_summary"):
        v = obj.get(key) or ""
        if not isinstance(v, str):
            raise BadOutput(f"'{key}' must be a string")
        summaries[key] = v
    return {"reasoning": str(obj.get("reasoning", ""))[:MAX_LEN], **summaries, "focus": str_list("focus"),
            "outlook": outlook, "projects": clean_projects, "watchouts": str_list("watchouts")}


# ---- date / time support check ---------------------------------------------------------
_TIME = re.compile(r"\b(\d{1,2}):(\d{2})\s?([ap]\.?m\.?)?", re.I)
_ISO = re.compile(r"\b\d{4}-(\d{2})-(\d{2})\b")
_SLASH = re.compile(r"\b(\d{1,2})/(\d{1,2})\b")
_MONTH_DAY = re.compile(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?\b", re.I)


def tokens(text: str) -> set[tuple]:
    """Dates as ('d', month, day) and times as ('t', 'HH:MM'). Day-of-week names are not
    checked: they cannot be wrong without the date beside them being wrong."""
    out: set[tuple] = set()
    for h, m, ap in _TIME.findall(text):
        hour = int(h)
        if ap:
            hour = hour % 12 + (12 if ap.lower().startswith("p") else 0)
        out.add(("t", f"{hour:02d}:{m}"))
    for m, d in _ISO.findall(text):
        out.add(("d", int(m), int(d)))
    for m, d in _SLASH.findall(text):
        out.add(("d", int(m), int(d)))
    for mon, d in _MONTH_DAY.findall(text):
        out.add(("d", MONTHS[mon.lower()[:3]], int(d)))
    return out


def allowed_tokens(facts: dict) -> set[tuple]:
    """Every date and time the facts contain, plus today."""
    blob = [facts["today"]]
    for e in facts["events"]:
        blob += [e["date"], e.get("until") or "", e["start_time"] or "", e["end_time"] or ""]
    for t in facts["tasks"]:
        blob += [t["due"] or "", t["title"], t["notes"]]
    for p in facts["projects"]:
        blob += [p.get("pushed", ""), p["name"], p.get("description", ""), *p.get("commits", [])]
        for n in p.get("recent_notes", []):
            blob += [n["updated"], n["title"], n["snippet"]]
    allowed = tokens("\n".join(blob))
    return allowed


# ---- cleaning + enforcement ------------------------------------------------------------
def _clean(s: str) -> str:
    s = re.sub(r"<[^>]*>", "", s)                    # no HTML in a Markdown note
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"^(?:[-*+>#]+\s*)+", "", s)          # a leading bullet/heading/quote marker
    return s[:MAX_LEN].rstrip()


def guard_ai(draft: dict, facts: dict) -> tuple[dict, list[str]]:
    """Returns (ai, removed): ai is {"focus", "outlook", "projects": {id: summary},
    "watchouts"}; removed lists why lines were dropped, for the footer."""
    allowed = allowed_tokens(facts)
    removed: list[str] = []

    def ok(text: str, where: str) -> str | None:
        text = _clean(text)
        if not text:
            return None
        extra = tokens(text) - allowed
        if extra:
            removed.append(f"{where}: date/time not in your data")
            return None
        return text

    focus = [t for t in (ok(x, "focus") for x in draft["focus"]) if t][:MAX_FOCUS]
    watch = [t for t in (ok(x, "watch-out") for x in draft["watchouts"]) if t][:MAX_WATCHOUTS]
    outlook = (ok(draft["outlook"], "outlook") or "") if facts["is_weekly"] else ""
    # A summary of nothing is invented by definition: keep one only if there are events to summarise.
    today = date.fromisoformat(facts["today"])
    day_summary = (ok(draft.get("day_summary", ""), "day summary") or "") if events_on(facts["events"], today) else ""
    irregular_summary = ((ok(draft.get("irregular_summary", ""), "irregular summary") or "")
                         if irregular_events(facts) else "")

    by_id = {p["id"]: p for p in facts["projects"]}
    summaries: dict[int, str] = {}
    for p in draft["projects"]:
        proj = by_id.get(p["id"])
        if proj is None or p["id"] in summaries:
            removed.append("project: unknown or duplicate id")
        elif proj.get("private"):
            continue  # nothing was shared about a private repo, so nothing can be said
        elif (s := ok(p["summary"], f"project {proj['name']}")):
            summaries[p["id"]] = s
    return {"focus": focus, "outlook": outlook, "day_summary": day_summary,
            "irregular_summary": irregular_summary, "projects": summaries, "watchouts": watch}, removed

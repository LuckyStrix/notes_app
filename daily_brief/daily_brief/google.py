"""Google Calendar and Tasks, read-only scopes.

The OAuth consent is a one-time step (`python -m daily_brief auth-google`) done on a machine
with a browser: Google does not allow the Calendar scope in the headless device flow. The
token file is copied into the data dir afterwards. The consent screen must be set to
"In production" in Google Cloud Console, or Google expires the refresh token after 7 days.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/tasks.readonly",
]


class GoogleError(Exception):
    """Token missing/expired or the API failed. Shown in the brief, never swallowed."""


# ---- pure parsing ----------------------------------------------------------------------
def parse_event(raw: dict, tz: ZoneInfo, calendar: str = "") -> dict | None:
    """Normalise one Calendar API event. Returns None for cancelled / declined events."""
    if raw.get("status") == "cancelled":
        return None
    for att in raw.get("attendees", []):
        if att.get("self") and att.get("responseStatus") == "declined":
            return None
    start, end = raw.get("start", {}), raw.get("end", {})
    ev = {
        "title": (raw.get("summary") or "(no title)").strip(),
        "location": (raw.get("location") or "").strip(),
        "calendar": calendar,
        "irregular": _irregular(raw, start),
    }
    if "date" in start:  # all-day; the API's end date is exclusive
        d = date.fromisoformat(start["date"])
        last = date.fromisoformat(end["date"]) - timedelta(days=1) if "date" in end else d
        ev.update(date=d.isoformat(), start_time=None, end_time=None,
                  until=last.isoformat() if last > d else None)
    elif "dateTime" in start:
        s = datetime.fromisoformat(start["dateTime"]).astimezone(tz)
        e = datetime.fromisoformat(end["dateTime"]).astimezone(tz) if "dateTime" in end else s
        ev.update(date=s.date().isoformat(), start_time=s.strftime("%H:%M"),
                  end_time=e.strftime("%H:%M"), until=None)
    else:
        return None
    return ev


def _instant(d: dict):
    """A comparable value for a Calendar start/originalStartTime: an aware datetime or a date."""
    if "dateTime" in d:
        return datetime.fromisoformat(d["dateTime"])
    return date.fromisoformat(d["date"]) if "date" in d else None


def _irregular(raw: dict, start: dict) -> bool:
    """One-offs and moved instances are irregular; an untouched instance of a recurring series
    is not. singleEvents=True expands a series into instances that carry `recurringEventId`,
    and a rescheduled instance's `originalStartTime` differs from its `start`."""
    if not raw.get("recurringEventId"):
        return True
    orig = raw.get("originalStartTime")
    try:
        return bool(orig) and _instant(orig) != _instant(start)
    except ValueError:
        return False


def parse_task(raw: dict, list_title: str = "") -> dict | None:
    if raw.get("status") == "completed" or not (raw.get("title") or "").strip():
        return None
    due = raw.get("due")  # RFC 3339 at midnight UTC: only the date part means anything
    return {
        "title": raw["title"].strip(),
        "due": due[:10] if due else None,
        "list": list_title,
        "notes": (raw.get("notes") or "").strip()[:200],
    }


# ---- calendar selection ----------------------------------------------------------------
def _cal_name(c: dict) -> str:
    # The primary calendar's own name is the account's email address; do not send that anywhere.
    return "Primary" if c.get("primary") else (c.get("summaryOverride") or c.get("summary") or c["id"])


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def resolve_calendars(available: list[dict], wanted: tuple[str, ...]) -> tuple[list[tuple[str, str]], list[str]]:
    """Maps the names/ids in Brief Settings to [(calendar id, label)]. Matching ignores case,
    spaces and punctuation ("carters events" finds "Carter's Events"); a unique partial match
    also works. `primary` is your main calendar. Pure."""
    resolved: list[tuple[str, str]] = []
    warnings: list[str] = []
    for w in wanted:
        match = None
        if w.lower() == "primary":
            match = next((c for c in available if c.get("primary")), None)
        match = match or next((c for c in available if c["id"] == w), None)
        if not match:
            nw = _norm(w)
            cands = ([c for c in available if _norm(_cal_name(c)) == nw]
                     or [c for c in available if nw and nw in _norm(_cal_name(c))])
            if len(cands) > 1:
                warnings.append(f"calendars: '{w}' matches several calendars ({', '.join(_cal_name(c) for c in cands)}); use the exact name")
                continue
            match = cands[0] if cands else None
        if not match:
            warnings.append(f"calendars: no calendar named '{w}' (`python -m daily_brief calendars` lists them)")
        elif all(match["id"] != r[0] for r in resolved):
            resolved.append((match["id"], _cal_name(match)))
    return resolved, warnings


# ---- API access ------------------------------------------------------------------------
def _credentials(token_path: Path):
    if not token_path.exists():
        raise GoogleError(f"no Google token at {token_path}; run `python -m daily_brief auth-google`")
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if not creds.valid:
        try:
            creds.refresh(Request())
        except Exception as exc:  # google.auth.exceptions.RefreshError and transport errors
            raise GoogleError(f"Google token could not be refreshed ({exc}); re-run auth-google") from exc
        token_path.write_text(creds.to_json())
    return creds


def fetch(token_path: Path, tz: ZoneInfo, calendars: tuple[str, ...], start: date, end: date):
    """Returns (events, tasks, warnings) for [start, end]. Raises GoogleError. The same event
    on two calendars (an invite you both received and your own copy) is kept once."""
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError

    creds = _credentials(token_path)
    t0 = datetime.combine(start, datetime.min.time(), tz).isoformat()
    t1 = datetime.combine(end + timedelta(days=1), datetime.min.time(), tz).isoformat()
    events, tasks, seen = [], [], set()
    try:
        cal = build("calendar", "v3", credentials=creds, cache_discovery=False)
        available = cal.calendarList().list(maxResults=250).execute().get("items", [])
        chosen, warnings = resolve_calendars(available, calendars)
        for cal_id, label in chosen:
            resp = cal.events().list(calendarId=cal_id, timeMin=t0, timeMax=t1, singleEvents=True,
                                     orderBy="startTime", maxResults=250).execute()
            for raw in resp.get("items", []):
                e = parse_event(raw, tz, label)
                key = e and (e["title"].lower(), e["date"], e["start_time"], e["end_time"], e["until"])
                if e and key not in seen:
                    seen.add(key)
                    events.append(e)
        svc = build("tasks", "v1", credentials=creds, cache_discovery=False)
        for tl in svc.tasklists().list(maxResults=50).execute().get("items", []):
            resp = svc.tasks().list(tasklist=tl["id"], showCompleted=False, showHidden=False,
                                    maxResults=100).execute()
            tasks += [t for t in (parse_task(r, tl.get("title", "")) for r in resp.get("items", [])) if t]
    except HttpError as exc:
        raise GoogleError(f"Google API error: {exc}") from exc
    return events, tasks, warnings


def list_calendars(token_path: Path) -> list[tuple[str, str]]:
    """[(label, id)] for every calendar the account can see, for the `calendars` command."""
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError

    try:
        cal = build("calendar", "v3", credentials=_credentials(token_path), cache_discovery=False)
        items = cal.calendarList().list(maxResults=250).execute().get("items", [])
    except HttpError as exc:
        raise GoogleError(f"Google API error: {exc}") from exc
    return [(_cal_name(c), c["id"]) for c in items]


def check_client_secret(path: Path) -> None:
    """Fail with a plain explanation if this is not the OAuth client JSON from Cloud Console.
    The usual mistake is passing a file that holds only the client id or secret text: Google
    ids start with a 12-digit number, which is why json.load used to die with 'Extra data:
    line 1 column 13'."""
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise GoogleError(f"cannot read {path}: {exc}") from exc
    try:
        data = json.loads(text)
    except ValueError:
        raise GoogleError(
            f"{path} is not JSON. It must be the file downloaded from Google Cloud Console "
            "(APIs & Services > Credentials > your OAuth client > Download JSON), not the client "
            "id or secret pasted into a file. It should start with {\"installed\": ..."
        ) from None
    if not isinstance(data, dict) or "installed" not in data:
        kind = next(iter(data), "?") if isinstance(data, dict) else type(data).__name__
        raise GoogleError(
            f"{path} has the wrong shape (top-level key '{kind}'). The OAuth client must be of type "
            "'Desktop app', whose JSON starts with {\"installed\": ...}. Create a new client of that type."
        )


def authorize(client_secret_path: Path, token_path: Path) -> None:
    """One-time browser consent. Run on a machine with a browser, then copy the token."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    check_client_secret(client_secret_path)

    flow = InstalledAppFlow.from_client_secrets_file(str(client_secret_path), SCOPES)
    creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json())
    token_path.chmod(0o600)

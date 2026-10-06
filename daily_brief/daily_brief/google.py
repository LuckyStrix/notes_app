"""Google Calendar and Tasks, read-only scopes.

The OAuth consent is a one-time step (`python -m daily_brief auth-google`) done on a machine
with a browser: Google does not allow the Calendar scope in the headless device flow. The
token file is copied into the data dir afterwards. The consent screen must be set to
"In production" in Google Cloud Console, or Google expires the refresh token after 7 days.
"""
from __future__ import annotations

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


# ---- API access ------------------------------------------------------------------------
def _credentials(token_path: Path):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    if not token_path.exists():
        raise GoogleError(f"no Google token at {token_path}; run `python -m daily_brief auth-google`")
    creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if not creds.valid:
        try:
            creds.refresh(Request())
        except Exception as exc:  # google.auth.exceptions.RefreshError and transport errors
            raise GoogleError(f"Google token could not be refreshed ({exc}); re-run auth-google") from exc
        token_path.write_text(creds.to_json())
    return creds


def fetch(token_path: Path, tz: ZoneInfo, calendars: tuple[str, ...], start: date, end: date):
    """Returns (events, tasks) for [start, end]. Raises GoogleError."""
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError

    creds = _credentials(token_path)
    t0 = datetime.combine(start, datetime.min.time(), tz).isoformat()
    t1 = datetime.combine(end + timedelta(days=1), datetime.min.time(), tz).isoformat()
    events, tasks = [], []
    try:
        cal = build("calendar", "v3", credentials=creds, cache_discovery=False)
        for cal_id in calendars:
            resp = cal.events().list(calendarId=cal_id, timeMin=t0, timeMax=t1, singleEvents=True,
                                     orderBy="startTime", maxResults=250).execute()
            name = resp.get("summary", cal_id)
            events += [e for e in (parse_event(r, tz, name) for r in resp.get("items", [])) if e]
        svc = build("tasks", "v1", credentials=creds, cache_discovery=False)
        for tl in svc.tasklists().list(maxResults=50).execute().get("items", []):
            resp = svc.tasks().list(tasklist=tl["id"], showCompleted=False, showHidden=False,
                                    maxResults=100).execute()
            tasks += [t for t in (parse_task(r, tl.get("title", "")) for r in resp.get("items", [])) if t]
    except HttpError as exc:
        raise GoogleError(f"Google API error: {exc}") from exc
    return events, tasks


def authorize(client_secret_path: Path, token_path: Path) -> None:
    """One-time browser consent. Run on a machine with a browser, then copy the token."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(str(client_secret_path), SCOPES)
    creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json())
    token_path.chmod(0o600)

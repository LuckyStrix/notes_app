"""GitHub repo activity. Private repos expose name and last-push date only.

That limit is deliberate: what is gathered here is sent to whichever providers 9router
routes to, and those may log it. Public repos are public anyway; private ones are not
described and their commit messages are never fetched.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import requests

API = "https://api.github.com"


class GitHubError(Exception):
    pass


def select_active(raw_repos: list[dict], owner: str, now: datetime, days: int) -> list[dict]:
    """Owned, non-fork, non-archived repos pushed to within `days`. Newest first. Pure."""
    cutoff = now - timedelta(days=days)
    out = []
    for r in raw_repos:
        if r.get("owner", {}).get("login", "").lower() != owner.lower():
            continue
        if r.get("fork") or r.get("archived") or not r.get("pushed_at"):
            continue
        pushed = datetime.fromisoformat(r["pushed_at"].replace("Z", "+00:00"))
        if pushed >= cutoff:
            out.append({"name": r["name"], "full_name": r["full_name"], "private": bool(r.get("private")),
                        "pushed": pushed.astimezone(now.tzinfo).date().isoformat(),
                        "description": (r.get("description") or "").strip()})
    return sorted(out, key=lambda r: r["pushed"], reverse=True)


def to_fact(repo: dict, commit_messages: list[str]) -> dict:
    """The only fields a repo contributes to the facts. Private -> no description/commits."""
    fact = {"name": repo["name"], "private": repo["private"], "pushed": repo["pushed"]}
    if not repo["private"]:
        fact["description"] = repo["description"][:200]
        fact["commits"] = [m[:120] for m in commit_messages[:5]]
    return fact


def _get(session, path: str, token: str, **params):
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        resp = session.get(API + path, headers=headers, params=params, timeout=30)
    except requests.RequestException as exc:
        raise GitHubError(f"GET {path}: {exc}") from exc
    if resp.status_code >= 400:
        raise GitHubError(f"GET {path}: HTTP {resp.status_code} {resp.text[:150]}")
    return resp.json()


def fetch(owner: str, token: str, now: datetime, days: int, session=None) -> list[dict]:
    """Repo facts, newest push first. With a token, private repos are included (name and
    date only); without one, only public repos are visible."""
    session = session or requests.Session()
    if token:
        raw = _get(session, "/user/repos", token, affiliation="owner", sort="pushed", per_page=100)
    else:
        raw = _get(session, f"/users/{owner}/repos", token, sort="pushed", per_page=100)
    facts = []
    for repo in select_active(raw, owner, now, days):
        msgs: list[str] = []
        if not repo["private"]:
            since = (now - timedelta(days=days)).astimezone().isoformat()
            commits = _get(session, f"/repos/{repo['full_name']}/commits", token, per_page=5, since=since)
            msgs = [c["commit"]["message"].splitlines()[0] for c in commits if c.get("commit")]
        facts.append(to_fact(repo, msgs))
    return facts

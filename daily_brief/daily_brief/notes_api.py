"""The only channel to the notes app. GET anything; writes only inside the Brief project.

The notes app has no auth (the tailnet is the boundary), so "the AI can only touch the
Brief project" is enforced here: every write goes through `_check_write`, which allows an
explicit list of (verb, path) shapes scoped to the Brief project, and there is no DELETE
or PUT at all. A unit test pins this down.
"""
from __future__ import annotations

import re

import requests

from .config import BRIEF_PROJECT, BRIEFS_GROUP


class NotesApiError(Exception):
    """The notes app is unreachable or answered with an error."""


class WriteNotAllowed(Exception):
    """A write outside the Brief project was attempted. Always a bug in this code."""


_NOTE_PATH = re.compile(r"^/notes/([0-9a-fA-F-]{36})$")


class NotesApi:
    def __init__(self, base_url: str, session=None, timeout: float = 30.0, brief_name: str = BRIEF_PROJECT):
        self.base_url = base_url.rstrip("/")
        self.session = session or requests.Session()
        self.timeout = timeout
        self.brief_name = brief_name
        self.brief_id: str | None = None
        self._brief_notes: set[str] = set()  # ids verified to live in the Brief project

    # ---- transport -------------------------------------------------------------------
    def _request(self, method: str, path: str, params=None, payload=None):
        try:
            resp = self.session.request(
                method, self.base_url + path, params=params, json=payload, timeout=self.timeout
            )
        except requests.RequestException as exc:
            raise NotesApiError(f"{method} {path}: {exc}") from exc
        if resp.status_code >= 400:
            raise NotesApiError(f"{method} {path}: HTTP {resp.status_code} {resp.text[:200]}")
        return resp.json() if resp.content else None

    def _get(self, path: str, **params):
        return self._request("GET", path, params=params or None)

    # ---- reads -----------------------------------------------------------------------
    def projects(self) -> list[dict]:
        return self._get("/projects")

    def notes(self, project_id: str, group_id: str | None = None) -> list[dict]:
        params = {"project_id": project_id}
        if group_id:
            params["group_id"] = group_id
        return self._get("/notes", **params)

    def note(self, note_id: str) -> dict:
        return self._get(f"/notes/{note_id}")

    def groups(self, project_id: str) -> list[dict]:
        return self._get(f"/projects/{project_id}/groups")

    # ---- the write guard -------------------------------------------------------------
    def _check_write(self, method: str, path: str, payload: dict) -> None:
        if method == "POST" and path == "/projects":
            if payload.get("name") == self.brief_name:
                return
        elif self.brief_id is None:
            pass  # nothing else is writable until the Brief project is known
        elif method == "POST" and path == "/notes":
            if payload.get("project_id") == self.brief_id:
                return
        elif method == "POST" and path == f"/projects/{self.brief_id}/groups":
            return
        elif method == "PATCH":
            m = _NOTE_PATH.match(path)
            if m and self._in_brief(m.group(1)):
                return
        raise WriteNotAllowed(f"{method} {path} is outside the {self.brief_name} project")

    def _in_brief(self, note_id: str) -> bool:
        if note_id not in self._brief_notes:
            if self.note(note_id).get("project_id") != self.brief_id:
                return False
            self._brief_notes.add(note_id)
        return True

    def _write(self, method: str, path: str, payload: dict):
        self._check_write(method, path, payload)
        return self._request(method, path, payload=payload)

    # ---- writes (Brief project only) -------------------------------------------------
    def ensure_brief_project(self) -> dict:
        for p in self.projects():
            if p["name"] == self.brief_name:
                self.brief_id = p["id"]
                return p
        p = self._write("POST", "/projects", {"name": self.brief_name,
                                              "description": "Daily planning brief and its controls."})
        self.brief_id = p["id"]
        return p

    def ensure_group(self, name: str = BRIEFS_GROUP) -> dict:
        assert self.brief_id, "call ensure_brief_project first"
        for g in self.groups(self.brief_id):
            if g["name"] == name:
                return g
        return self._write("POST", f"/projects/{self.brief_id}/groups", {"name": name})

    def brief_notes(self) -> list[dict]:
        assert self.brief_id, "call ensure_brief_project first"
        notes = self.notes(self.brief_id)
        self._brief_notes.update(n["id"] for n in notes)
        return notes

    def create_note(self, title: str, body: str, group_id: str | None = None) -> dict:
        assert self.brief_id, "call ensure_brief_project first"
        payload = {"project_id": self.brief_id, "type": "text", "title": title, "body": body}
        if group_id:
            payload["group_id"] = group_id
        note = self._write("POST", "/notes", payload)
        self._brief_notes.add(note["id"])
        return note

    def update_note(self, note_id: str, body: str, title: str | None = None) -> dict:
        # force_version: keep a recovery point for the notes people edit by hand.
        payload = {"body": body, "force_version": True}
        if title is not None:
            payload["title"] = title
        return self._write("PATCH", f"/notes/{note_id}", payload)

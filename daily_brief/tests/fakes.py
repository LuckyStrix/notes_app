"""In-memory stand-in for the notes app, with the same write guard semantics as NotesApi."""
from daily_brief.notes_api import NotesApiError


class FakeNotesApi:
    def __init__(self, other_projects=None):
        self.brief_id = None
        self._notes: dict[str, dict] = {}
        self._n = 0
        self.groups_ = []
        self.other = other_projects or []      # [{"id","name","description","notes":[...]}]
        self.writes = []                       # (verb, note id)

    def _id(self):
        self._n += 1
        return f"{self._n:08d}-0000-0000-0000-000000000000"

    def ensure_brief_project(self):
        self.brief_id = "b0000000-0000-0000-0000-000000000000"
        return {"id": self.brief_id, "name": "Brief"}

    def ensure_group(self, name="Briefs"):
        if not self.groups_:
            self.groups_.append({"id": self._id(), "name": name})
        return self.groups_[0]

    def projects(self):
        return [{"id": p["id"], "name": p["name"], "description": p.get("description")} for p in self.other]

    def notes(self, project_id, group_id=None):
        for p in self.other:
            if p["id"] == project_id:
                return p["notes"]
        raise NotesApiError("no such project")

    def brief_notes(self):
        return list(self._notes.values())

    def note(self, note_id):
        if note_id not in self._notes:
            raise NotesApiError(f"GET /notes/{note_id}: HTTP 404")
        return dict(self._notes[note_id])

    def create_note(self, title, body, group_id=None):
        n = {"id": self._id(), "title": title, "body": body, "project_id": self.brief_id, "group_id": group_id}
        self._notes[n["id"]] = n
        self.writes.append(("create", n["id"]))
        return dict(n)

    def update_note(self, note_id, body, title=None):
        self._notes[note_id]["body"] = body
        self.writes.append(("update", note_id))
        return dict(self._notes[note_id])

    def by_title(self, title):
        return next((n for n in self._notes.values() if n["title"] == title), None)

import unittest

from daily_brief.notes_api import NotesApi, NotesApiError, WriteNotAllowed

BRIEF = "b" * 8 + "-" + "0" * 4 + "-" + "0" * 4 + "-" + "0" * 4 + "-" + "0" * 12
OTHER = "a" * 8 + "-" + "0" * 4 + "-" + "0" * 4 + "-" + "0" * 4 + "-" + "0" * 12
NOTE_IN_OTHER = "c" * 8 + "-" + "0" * 4 + "-" + "0" * 4 + "-" + "0" * 4 + "-" + "0" * 12


class FakeResp:
    def __init__(self, data, status=200):
        self.data, self.status_code, self.text = data, status, str(data)
        self.content = b"x" if data is not None else b""

    def json(self):
        return self.data


class FakeSession:
    """Routes by (method, path); records every call."""

    def __init__(self):
        self.calls = []
        self.routes = {
            ("GET", "/projects"): [{"id": BRIEF, "name": "Brief"}, {"id": OTHER, "name": "Physics"}],
            ("GET", f"/notes/{NOTE_IN_OTHER}"): {"id": NOTE_IN_OTHER, "project_id": OTHER},
        }

    def request(self, method, url, params=None, json=None, timeout=None):
        path = url.replace("http://notes", "")
        self.calls.append((method, path, json))
        if (method, path) in self.routes:
            return FakeResp(self.routes[(method, path)])
        if method == "POST" and path == "/notes":
            return FakeResp({"id": "n" * 8 + "-" + "0" * 4 + "-" + "0" * 4 + "-" + "0" * 4 + "-" + "0" * 12, **json})
        return FakeResp({"detail": "nope"}, 404)


def make():
    s = FakeSession()
    api = NotesApi("http://notes", session=s)
    return api, s


class WriteGuardTests(unittest.TestCase):
    def test_nothing_writable_before_brief_project_known(self):
        api, _ = make()
        with self.assertRaises(WriteNotAllowed):
            api._write("POST", "/notes", {"project_id": BRIEF, "type": "text", "title": "t"})

    def test_create_in_brief_ok(self):
        api, s = make()
        api.ensure_brief_project()
        note = api.create_note("t", "b")
        self.assertEqual(note["project_id"], BRIEF)

    def test_post_note_to_another_project_refused(self):
        api, s = make()
        api.ensure_brief_project()
        with self.assertRaises(WriteNotAllowed):
            api._write("POST", "/notes", {"project_id": OTHER, "type": "text", "title": "x"})
        self.assertFalse([c for c in s.calls if c[0] == "POST"])

    def test_patch_note_in_another_project_refused(self):
        api, s = make()
        api.ensure_brief_project()
        with self.assertRaises(WriteNotAllowed):
            api.update_note(NOTE_IN_OTHER, "overwrite")
        self.assertFalse([c for c in s.calls if c[0] == "PATCH"])

    def test_creating_a_project_other_than_brief_refused(self):
        api, _ = make()
        with self.assertRaises(WriteNotAllowed):
            api._write("POST", "/projects", {"name": "Physics 2"})

    def test_no_delete_or_put_verbs_exist_or_pass_the_guard(self):
        api, _ = make()
        api.ensure_brief_project()
        for method in ("DELETE", "PUT"):
            with self.assertRaises(WriteNotAllowed):
                api._write(method, f"/notes/{NOTE_IN_OTHER}", {})
        self.assertFalse([m for m in dir(api) if m.lstrip("_") in ("delete", "put", "delete_note")])

    def test_http_error_becomes_notes_api_error(self):
        api, _ = make()
        with self.assertRaises(NotesApiError):
            api.note("missing")


if __name__ == "__main__":
    unittest.main()

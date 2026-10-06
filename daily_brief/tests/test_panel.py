import json
import unittest

import requests

from daily_brief.panel import Router, build_messages, run_panel
from tests.test_guard import make_facts

GOOD = {"reasoning": "r", "focus": ["Exam 1 on Oct 9"], "outlook": "", "projects": [{"id": 1, "summary": "Fixed a bug."}], "watchouts": []}


class Resp:
    def __init__(self, content=None, status=200):
        self.status_code, self.text = status, content or ""
        self._content = content

    def json(self):
        return {"choices": [{"message": {"content": self._content}}]}


class FakeSession:
    """script: model -> list of replies (str content, int status, or an Exception)."""

    def __init__(self, script):
        self.script, self.calls = script, []

    def post(self, url, json=None, headers=None, timeout=None):
        model = json["model"]
        self.calls.append((model, json["messages"]))
        reply = self.script[model].pop(0)
        if isinstance(reply, Exception):
            raise reply
        if isinstance(reply, int):
            return Resp("", reply)
        return Resp(reply)


def panel(script, drafters=("a", "b"), editor="e"):
    s = FakeSession(script)
    router = Router("http://r/v1", "k", session=s, sleep=lambda _: None)
    return run_panel(make_facts(), drafters, editor, {"about": "Student.", "drafter": "Be terse."}, router), s


class PanelTests(unittest.TestCase):
    def test_happy_path_editor_output_is_used_and_guarded(self):
        edited = {**GOOD, "focus": ["Exam 1 on Oct 9", "Invented deadline Oct 20"]}
        r, _ = panel({"a": [json.dumps(GOOD)], "b": [json.dumps(GOOD)], "e": [json.dumps(edited)]})
        self.assertTrue(r.editor_ok)
        self.assertEqual(r.ai["focus"], ["Exam 1 on Oct 9"])
        self.assertEqual(len(r.removed), 1)
        self.assertTrue(any("removed by checks" in n for n in r.notes))

    def test_editor_sees_all_drafts_by_letter_only(self):
        _, s = panel({"a": [json.dumps(GOOD)], "b": [json.dumps(GOOD)], "e": [json.dumps(GOOD)]})
        editor_user = [m for model, m in s.calls if model == "e"][0][1]["content"]
        self.assertIn("DRAFT A", editor_user)
        self.assertIn("DRAFT B", editor_user)

    def test_one_drafter_down_others_carry_on(self):
        r, _ = panel({"a": [requests.ConnectionError("down"), requests.ConnectionError("down")],
                      "b": [json.dumps(GOOD)], "e": [json.dumps(GOOD)]})
        self.assertEqual([d.ok for d in r.drafts], [False, True])
        self.assertIsNotNone(r.ai)

    def test_bad_output_retried_once_with_the_error(self):
        r, s = panel({"a": ["not json", json.dumps(GOOD)], "b": [json.dumps(GOOD)], "e": [json.dumps(GOOD)]})
        self.assertTrue(all(d.ok for d in r.drafts))
        retry = [m for model, m in s.calls if model == "a"][1]
        self.assertIn("not usable", retry[-1]["content"])

    def test_server_error_retried_then_succeeds(self):
        r, _ = panel({"a": [500, json.dumps(GOOD)], "b": [json.dumps(GOOD)], "e": [json.dumps(GOOD)]})
        self.assertTrue(all(d.ok for d in r.drafts))

    def test_editor_failure_falls_back_to_first_draft_and_says_so(self):
        r, _ = panel({"a": [json.dumps(GOOD)], "b": [json.dumps(GOOD)], "e": ["junk", "junk"]})
        self.assertFalse(r.editor_ok)
        self.assertIsNotNone(r.ai)
        self.assertTrue(any("Editor failed" in n for n in r.notes))

    def test_all_drafters_failing_gives_no_ai_and_no_exception(self):
        r, _ = panel({"a": ["x", "x"], "b": [401], "e": []})
        self.assertIsNone(r.ai)
        self.assertTrue(any("unavailable" in n for n in r.notes))

    def test_no_models_configured_is_a_note_not_an_error(self):
        s = FakeSession({})
        r = run_panel(make_facts(), (), "", {}, Router("http://r/v1", "", session=s))
        self.assertIsNone(r.ai)
        self.assertEqual(s.calls, [])

    def test_instructions_reach_the_system_prompt(self):
        sysmsg = build_messages("drafter", make_facts(), {"about": "Student.", "drafter": "Be terse."})[0]["content"]
        self.assertIn("Student.", sysmsg)
        self.assertIn("Be terse.", sysmsg)


if __name__ == "__main__":
    unittest.main()

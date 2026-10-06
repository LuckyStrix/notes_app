import json
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from daily_brief.config import Settings
from daily_brief.gather import build_facts
from daily_brief.guard import BadOutput, extract_json, guard_ai, tokens, validate_draft

NOW = datetime(2026, 10, 7, 6, 0, tzinfo=ZoneInfo("America/New_York"))


def make_facts(is_monday=False):
    events = [{"title": "Exam 1", "location": "", "calendar": "", "date": "2026-10-09", "start_time": "14:00",
               "end_time": "15:30", "until": None}]
    tasks = [{"title": "Lab report", "due": "2026-10-08", "list": "", "notes": ""}]
    repos = [{"name": "pub", "private": False, "pushed": "2026-10-06", "description": "", "commits": ["Fix bug"]},
             {"name": "priv", "private": True, "pushed": "2026-10-05"}]
    f = build_facts(NOW, Settings(), events, tasks, repos, [], [])
    f["is_weekly"] = is_monday
    return f


def draft(**kw):
    base = {"reasoning": "r", "focus": [], "outlook": "", "projects": [], "watchouts": []}
    return {**base, **kw}


class ExtractJsonTests(unittest.TestCase):
    def test_fenced_and_chatty(self):
        raw = 'Sure! ```json\n{"focus": ["a {brace} in a string"], "x": {"y": 1}}\n``` hope that helps'
        self.assertEqual(extract_json(raw)["focus"], ["a {brace} in a string"])

    def test_no_json_and_truncated(self):
        for raw in ("nothing here", '{"focus": ["cut off'):
            with self.assertRaises(BadOutput):
                extract_json(raw)


class ValidateTests(unittest.TestCase):
    def test_missing_focus_rejected(self):
        with self.assertRaises(BadOutput):
            validate_draft({"reasoning": "x"})

    def test_wrong_types_rejected(self):
        for bad in ({"focus": [1]}, {"focus": [], "projects": "x"}, {"focus": [], "projects": [{"id": "a", "summary": "s"}]}):
            with self.assertRaises(BadOutput):
                validate_draft(bad)

    def test_long_answers_are_not_rejected(self):
        self.assertEqual(len(validate_draft({"focus": ["x" * 5000]})["focus"][0]), 5000)


class TokenTests(unittest.TestCase):
    def test_times_and_dates_normalised(self):
        self.assertEqual(tokens("at 2:00 PM"), {("t", "14:00")})
        self.assertEqual(tokens("12:05 am"), {("t", "00:05")})
        self.assertEqual(tokens("due Oct 9 or 10/9 or 2026-10-09"), {("d", 10, 9)})
        self.assertEqual(tokens("September 3rd"), {("d", 9, 3)})
        self.assertEqual(tokens("moved to Oct 12th"), {("d", 10, 12)})


class GuardTests(unittest.TestCase):
    def test_supported_dates_and_times_pass(self):
        ai, removed = guard_ai(draft(focus=["Exam 1 on Oct 9 at 2:00 pm", "Finish the lab report (due 10/8)"]), make_facts())
        self.assertEqual(len(ai["focus"]), 2)
        self.assertEqual(removed, [])

    def test_invented_date_or_time_dropped_and_counted(self):
        ai, removed = guard_ai(draft(focus=["Exam moved to Oct 12", "Study for the 3:15 review", "Plain priority"]), make_facts())
        self.assertEqual(ai["focus"], ["Plain priority"])
        self.assertEqual(len(removed), 2)

    def test_private_repo_summary_dropped_without_counting_as_removed(self):
        ai, removed = guard_ai(draft(projects=[{"id": 1, "summary": "Fixed a bug."}, {"id": 2, "summary": "Built a secret thing."}]), make_facts())
        self.assertEqual(ai["projects"], {1: "Fixed a bug."})
        self.assertEqual(removed, [])

    def test_unknown_and_duplicate_project_ids(self):
        ai, removed = guard_ai(draft(projects=[{"id": 9, "summary": "x"}, {"id": 1, "summary": "a"}, {"id": 1, "summary": "b"}]), make_facts())
        self.assertEqual(ai["projects"], {1: "a"})
        self.assertEqual(len(removed), 2)

    def test_outlook_only_kept_on_weekly_day(self):
        self.assertEqual(guard_ai(draft(outlook="Busy week."), make_facts(False))[0]["outlook"], "")
        self.assertEqual(guard_ai(draft(outlook="Busy week."), make_facts(True))[0]["outlook"], "Busy week.")

    def test_markdown_and_html_stripped_and_lists_capped(self):
        ai, _ = guard_ai(draft(focus=["## Heading <b>bold</b>", *[f"item {i}" for i in range(10)]]), make_facts())
        self.assertEqual(ai["focus"][0], "Heading bold")
        self.assertEqual(len(ai["focus"]), 5)


if __name__ == "__main__":
    unittest.main()

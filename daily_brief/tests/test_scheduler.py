import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

from daily_brief import github, google
from daily_brief.config import Env
from daily_brief.config import NOTE_CONTROL
from daily_brief.control import (DEFAULT_INSTRUCTIONS_NOTE, DEFAULTS, control_result, parse_command,
                                 parse_instructions, update_if_changed)
from daily_brief.panel import Router
from daily_brief.scheduler import MAX_ATTEMPTS, Scheduler, State, is_due
from tests.fakes import FakeNotesApi
from tests.test_panel import FakeSession, GOOD

TZ = ZoneInfo("America/New_York")


def at(h, m=0, day=7):
    return datetime(2026, 10, day, h, m, tzinfo=TZ)


class IsDueTests(unittest.TestCase):
    def test_before_run_time_not_due(self):
        self.assertFalse(is_due(at(5, 59), "06:00", State()))

    def test_after_run_time_and_new_day_is_due_including_catch_up(self):
        self.assertTrue(is_due(at(6, 0), "06:00", State()))
        self.assertTrue(is_due(at(15, 0), "06:00", State(date="2026-10-06")))  # PC was off at 6am

    def test_done_today_not_due_again(self):
        self.assertFalse(is_due(at(9), "06:00", State(date="2026-10-07", attempts=1)))

    def test_incomplete_retried_after_30_min_up_to_max(self):
        s = State(date="2026-10-07", attempts=1, degraded=True, last_attempt=at(6).isoformat())
        self.assertFalse(is_due(at(6, 29), "06:00", s))
        self.assertTrue(is_due(at(6, 30), "06:00", s))
        s.attempts = MAX_ATTEMPTS
        self.assertFalse(is_due(at(12), "06:00", s))


class ControlParsingTests(unittest.TestCase):
    def test_commands(self):
        self.assertEqual(parse_command("# Brief Control\n\nType `run` to go\n\nrun\n"), "run")
        self.assertEqual(parse_command("Dry run\n"), "dry-run")
        self.assertEqual(parse_command("dry-run"), "dry-run")
        self.assertIsNone(parse_command("# Brief Control\n\nType `run` (write today's brief now)\n"))

    def test_command_typed_at_the_end_of_the_seeded_note_is_seen(self):
        # The seeded note ends with a '---' rule; the obvious place to type is below it.
        self.assertEqual(parse_command(DEFAULTS[NOTE_CONTROL] + "run"), "run")
        self.assertEqual(parse_command(DEFAULTS[NOTE_CONTROL] + "\ndry run\n"), "dry-run")

    def test_a_result_can_never_contain_a_command_line(self):
        self.assertIsNone(parse_command(control_result("Saved.\nrun\ndry run\n- [ ] run")))

    def test_instruction_sections(self):
        got = parse_instructions(DEFAULT_INSTRUCTIONS_NOTE)
        self.assertEqual(set(got), {"about", "drafter", "editor"})
        self.assertIn("6am", got["drafter"])
        self.assertNotIn("Editor", got["drafter"])


class TickTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = Env(Path(self.tmp.name), "http://n", "http://r/v1", "", "")
        self.api = FakeNotesApi()
        self.session = FakeSession({"d1": [json.dumps(GOOD)] * 5, "d2": [json.dumps(GOOD)] * 5, "ed": [json.dumps(GOOD)] * 5})
        self.sched = Scheduler(self.env, self.api, Router("http://r/v1", "", session=self.session, sleep=lambda _: None), log=lambda *_: None)
        patches = [mock.patch.object(google, "fetch", return_value=([], [])),
                   mock.patch.object(github, "fetch", return_value=[{"name": "pub", "private": False, "pushed": "2026-10-06", "description": "", "commits": ["Fix bug"]}])]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)

    def configure(self, text):
        self.sched.tick(at(5))  # seeds the control notes
        self.api.update_note(self.api.by_title("Brief Settings")["id"], text)

    def test_first_tick_seeds_the_four_control_notes_and_runs_nothing_early(self):
        self.sched.tick(at(5))
        self.assertEqual({n["title"] for n in self.api.brief_notes()},
                         {"Brief Instructions", "Brief Settings", "Brief Control", "Brief Status"})
        self.assertIsNone(self.api.by_title("Daily Brief 2026-10-07"))

    def test_scheduled_run_creates_dated_note_once_per_day(self):
        self.configure("drafters: d1, d2\neditor: ed")
        self.sched.tick(at(6, 1))
        note = self.api.by_title("Daily Brief 2026-10-07")
        self.assertIn("Fixed a bug.", note["body"])
        before = len(self.session.calls)
        self.sched.tick(at(7))
        self.assertEqual(len(self.session.calls), before)  # not run again
        self.assertEqual(len([n for n in self.api.brief_notes() if n["title"].startswith("Daily Brief")]), 1)

    def test_dry_run_command_saves_no_brief_and_returns_preview_in_control_note(self):
        self.configure("drafters: d1\neditor: ed")
        self.api.update_note(self.api.by_title("Brief Control")["id"], "# Brief Control\n\ndry run\n")
        self.sched.tick(at(5))
        self.assertIsNone(self.api.by_title("Daily Brief 2026-10-07"))
        control = self.api.by_title("Brief Control")["body"]
        self.assertIn("## Today", control)
        self.assertIsNone(parse_command(control))  # the command is gone, so it won't re-run

    def test_command_cleared_even_if_the_run_crashes(self):
        self.configure("drafters: d1\neditor: ed")
        self.api.update_note(self.api.by_title("Brief Control")["id"], "run\n")
        with mock.patch("daily_brief.scheduler.run_brief", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                self.sched.tick(at(5))
        self.assertIsNone(parse_command(self.api.by_title("Brief Control")["body"]))

    def test_google_failure_still_writes_a_flagged_brief_and_marks_it_for_retry(self):
        self.configure("drafters: d1\neditor: ed")
        with mock.patch.object(google, "fetch", side_effect=google.GoogleError("token expired")):
            self.sched.tick(at(6, 1))
        self.assertIn("⚠ Google Calendar and Tasks unavailable: token expired", self.api.by_title("Daily Brief 2026-10-07")["body"])
        state = State.load(self.sched.state_path)
        self.assertTrue(state.degraded)
        self.sched.tick(at(6, 40))  # retry updates the same note in place
        self.assertEqual(len([n for n in self.api.brief_notes() if n["title"].startswith("Daily Brief")]), 1)

    def test_update_if_changed_skips_identical_body(self):
        self.sched.tick(at(5))
        status = self.api.by_title("Brief Status")
        writes = len(self.api.writes)
        update_if_changed(self.api, status, status["body"] + "\n")  # only whitespace differs
        self.assertEqual(len(self.api.writes), writes)
        update_if_changed(self.api, status, "something new")
        self.assertEqual(len(self.api.writes), writes + 1)

    def test_bad_settings_reported_in_status_and_defaults_used(self):
        self.configure("run_time: soon")
        self.sched.tick(at(6, 1))
        self.assertIn("run_time", self.api.by_title("Brief Status")["body"])


if __name__ == "__main__":
    unittest.main()

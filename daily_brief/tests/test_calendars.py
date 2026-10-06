import importlib.util
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

from daily_brief.config import Settings
from daily_brief.gather import build_facts
from daily_brief import google
from daily_brief.google import parse_event, resolve_calendars
from daily_brief.guard import guard_ai, validate_draft
from daily_brief.render import irregular_events, render_brief

TZ = ZoneInfo("America/New_York")
NOW = datetime(2026, 10, 7, 6, 0, tzinfo=TZ)  # a Wednesday; its week ends Sunday Oct 11

AVAILABLE = [
    {"id": "me@example.com", "summary": "me@example.com", "primary": True},
    {"id": "abc@group.calendar.google.com", "summary": "Carter's Events"},
    {"id": "def@group.calendar.google.com", "summary": "Carter's Classes", "summaryOverride": "Classes"},
    {"id": "ghi@group.calendar.google.com", "summary": "Birthdays"},
    {"id": "jkl@group.calendar.google.com", "summary": "Carter's Travel"},
]


def raw(start, end=None, **kw):
    return {"summary": "x", "start": {"dateTime": start}, "end": {"dateTime": end or start}, **kw}


class IrregularTests(unittest.TestCase):
    def test_one_off_is_irregular(self):
        self.assertTrue(parse_event(raw("2026-10-07T09:00:00-04:00"), TZ)["irregular"])

    def test_untouched_recurring_instance_is_regular(self):
        e = parse_event(raw("2026-10-07T09:00:00-04:00", recurringEventId="r1",
                            originalStartTime={"dateTime": "2026-10-07T09:00:00-04:00"}), TZ)
        self.assertFalse(e["irregular"])

    def test_same_instant_in_another_utc_offset_is_still_regular(self):
        e = parse_event(raw("2026-10-07T09:00:00-04:00", recurringEventId="r1",
                            originalStartTime={"dateTime": "2026-10-07T13:00:00Z"}), TZ)
        self.assertFalse(e["irregular"])

    def test_moved_recurring_instance_is_irregular(self):
        e = parse_event(raw("2026-10-07T15:00:00-04:00", recurringEventId="r1",
                            originalStartTime={"dateTime": "2026-10-07T09:00:00-04:00"}), TZ)
        self.assertTrue(e["irregular"])

    def test_all_day_recurring_regular_and_moved(self):
        base = {"summary": "x", "recurringEventId": "r", "end": {"date": "2026-10-08"}}
        same = parse_event({**base, "start": {"date": "2026-10-07"}, "originalStartTime": {"date": "2026-10-07"}}, TZ)
        moved = parse_event({**base, "start": {"date": "2026-10-07"}, "originalStartTime": {"date": "2026-10-06"}}, TZ)
        self.assertFalse(same["irregular"])
        self.assertTrue(moved["irregular"])


class ResolveCalendarsTests(unittest.TestCase):
    def test_primary_and_a_name_with_different_punctuation(self):
        got, w = resolve_calendars(AVAILABLE, ("primary", "carters events"))
        self.assertEqual(got, [("me@example.com", "Primary"), ("abc@group.calendar.google.com", "Carter's Events")])
        self.assertEqual(w, [])

    def test_primary_label_never_contains_the_account_email(self):
        got, _ = resolve_calendars(AVAILABLE, ("primary",))
        self.assertNotIn("@", got[0][1])

    def test_exact_id_and_override_name(self):
        got, _ = resolve_calendars(AVAILABLE, ("ghi@group.calendar.google.com", "classes"))
        self.assertEqual([g[1] for g in got], ["Birthdays", "Classes"])

    def test_ambiguous_partial_and_unknown_warn(self):
        got, w = resolve_calendars(AVAILABLE, ("carter", "nonexistent"))
        self.assertEqual(got, [])
        self.assertEqual(len(w), 2)
        self.assertIn("several calendars", w[0])
        self.assertIn("calendars` lists them", w[1])

    def test_duplicates_collapse(self):
        got, _ = resolve_calendars(AVAILABLE, ("primary", "primary"))
        self.assertEqual(len(got), 1)


def ev(date, start="09:00", end="10:00", title="Thing", cal="Primary", irregular=False, until=None):
    return {"title": title, "location": "", "calendar": cal, "date": date, "start_time": start,
            "end_time": end, "until": until, "irregular": irregular}


def facts(events):
    return build_facts(NOW, Settings(), events, [], [], [], [])


class IrregularRenderTests(unittest.TestCase):
    def test_lists_only_irregular_events_through_sunday(self):
        f = facts([ev("2026-10-07", title="Weekly lecture"), ev("2026-10-08", title="Dentist", irregular=True),
                   ev("2026-10-12", title="Next week one-off", irregular=True)])
        self.assertEqual([e["title"] for _, e in irregular_events(f)], ["Dentist"])
        out = render_brief(f, None, [])
        section = out.split("## Out of the ordinary this week")[1].split("## Rest")[0]
        self.assertIn("Dentist", section)
        self.assertNotIn("Weekly lecture", section)
        self.assertNotIn("Next week", section)

    def test_classes_never_irregular(self):
        f = facts([ev("2026-10-08", title="CS 201 Lecture", irregular=True),
                   ev("2026-10-08", title="Dentist", irregular=True),
                   ev("2026-10-09", title="Exam", cal="Classes", irregular=True)])
        self.assertEqual([e["title"] for _, e in irregular_events(f)], ["Dentist"])

    def test_no_irregular_events_means_no_section(self):
        self.assertNotIn("Out of the ordinary", render_brief(facts([ev("2026-10-07")]), None, []))

    def test_calendar_tag_only_when_several_calendars(self):
        one = render_brief(facts([ev("2026-10-07")]), None, [])
        two = render_brief(facts([ev("2026-10-07"), ev("2026-10-08", cal="Carter's Events")]), None, [])
        self.assertNotIn("_(Primary)_", one)
        self.assertIn("_(Primary)_", two)
        self.assertIn("_(Carter's Events)_", two)

    def test_summaries_appear_in_their_sections(self):
        f = facts([ev("2026-10-07"), ev("2026-10-09", title="Exam", irregular=True)])
        ai = {"day_summary": "A light day.", "irregular_summary": "One exam Friday."}
        out = render_brief(f, ai, [])
        self.assertIn("## Today\n\nA light day.", out)
        self.assertIn("## Out of the ordinary this week\n\nOne exam Friday.", out)


class _Call:
    def __init__(self, data):
        self.data = data

    def execute(self):
        return self.data


class FakeService:
    """Just enough of the Calendar/Tasks client: .calendarList().list(), .events().list(), ..."""

    def __init__(self, kind, events_by_cal):
        self.kind, self.events_by_cal, self.asked = kind, events_by_cal, []

    def calendarList(self):
        return self

    def events(self):
        return self

    def tasklists(self):
        return self

    def tasks(self):
        return self

    def list(self, **kw):
        if "calendarId" in kw:
            self.asked.append(kw["calendarId"])
            return _Call({"items": self.events_by_cal[kw["calendarId"]]})
        if "tasklist" in kw:
            return _Call({"items": [{"title": "Essay", "due": "2026-10-09T00:00:00.000Z"},
                                    {"title": "Done", "status": "completed"}]})
        if self.kind == "tasks":
            return _Call({"items": [{"id": "tl1", "title": "My Tasks"}]})
        return _Call({"items": AVAILABLE})


@unittest.skipUnless(importlib.util.find_spec("googleapiclient"), "google client libraries not installed")
class FetchTests(unittest.TestCase):
    def run_fetch(self, wanted):
        lecture = {"summary": "Lecture", "recurringEventId": "r1", "start": {"dateTime": "2026-10-07T09:00:00-04:00"},
                   "end": {"dateTime": "2026-10-07T10:00:00-04:00"}, "originalStartTime": {"dateTime": "2026-10-07T09:00:00-04:00"}}
        exam = {"summary": "Exam", "start": {"dateTime": "2026-10-09T14:00:00-04:00"}, "end": {"dateTime": "2026-10-09T15:30:00-04:00"}}
        by_cal = {"me@example.com": [lecture, exam], "abc@group.calendar.google.com": [exam]}  # same exam on both
        cal = FakeService("calendar", by_cal)
        tasks = FakeService("tasks", {})
        with mock.patch.object(google, "_credentials", return_value=object()), \
             mock.patch("googleapiclient.discovery.build", side_effect=lambda name, *a, **k: cal if name == "calendar" else tasks):
            return google.fetch(Path("t.json"), TZ, wanted, date(2026, 10, 7), date(2026, 10, 21)), cal

    def test_both_calendars_read_duplicates_dropped_irregular_flagged(self):
        (events, tasks, warnings), cal = self.run_fetch(("primary", "carters events"))
        self.assertEqual(cal.asked, ["me@example.com", "abc@group.calendar.google.com"])
        self.assertEqual([(e["title"], e["calendar"], e["irregular"]) for e in events],
                         [("Lecture", "Primary", False), ("Exam", "Primary", True)])
        self.assertEqual([(t["title"], t["due"]) for t in tasks], [("Essay", "2026-10-09")])
        self.assertEqual(warnings, [])

    def test_unknown_calendar_name_warns_but_others_still_read(self):
        (events, _, warnings), cal = self.run_fetch(("primary", "no such calendar"))
        self.assertEqual(len(events), 2)
        self.assertEqual(len(warnings), 1)


def draft(**kw):
    return {"reasoning": "", "focus": [], "outlook": "", "projects": [], "watchouts": [],
            "day_summary": "", "irregular_summary": "", **kw}


class SummaryGuardTests(unittest.TestCase):
    def test_summary_of_nothing_is_dropped(self):
        f = facts([])
        ai, _ = guard_ai(draft(day_summary="A busy day.", irregular_summary="A trip."), f)
        self.assertEqual((ai["day_summary"], ai["irregular_summary"]), ("", ""))

    def test_summaries_kept_when_there_are_events_and_times_match(self):
        f = facts([ev("2026-10-07", "09:00", "10:00"), ev("2026-10-09", "14:00", "15:30", title="Exam", irregular=True)])
        ai, removed = guard_ai(draft(day_summary="One class at 9:00, then free.",
                                     irregular_summary="Exam Friday at 2:00 pm."), f)
        self.assertEqual(removed, [])
        self.assertTrue(ai["day_summary"] and ai["irregular_summary"])

    def test_invented_time_in_a_summary_is_dropped(self):
        f = facts([ev("2026-10-07", "09:00", "10:00")])
        ai, removed = guard_ai(draft(day_summary="Class at 9:00 and a meeting at 4:45."), f)
        self.assertEqual(ai["day_summary"], "")
        self.assertEqual(len(removed), 1)

    def test_old_drafts_without_the_new_fields_still_validate(self):
        got = validate_draft({"focus": ["x"]})
        self.assertEqual((got["day_summary"], got["irregular_summary"]), ("", ""))


if __name__ == "__main__":
    unittest.main()

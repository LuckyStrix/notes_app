import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from daily_brief.config import Settings
from daily_brief.gather import build_facts
from daily_brief.github import select_active, to_fact
from daily_brief.google import parse_event, parse_task
from daily_brief.render import render_brief

TZ = ZoneInfo("America/New_York")
NOW = datetime(2026, 10, 7, 6, 0, tzinfo=TZ)  # a Wednesday


def ev(date, start="09:00", end="10:00", title="Lecture", loc="", until=None):
    return {"title": title, "location": loc, "calendar": "c", "date": date, "start_time": start,
            "end_time": end, "until": until}


def task(title, due, lst="My Tasks"):
    return {"title": title, "due": due, "list": lst, "notes": ""}


def facts(events=(), tasks=(), repos=(), projects=(), errors=()):
    return build_facts(NOW, Settings(), list(events), list(tasks), list(repos), list(projects), list(errors))


class ParseTests(unittest.TestCase):
    def test_timed_event_converted_to_local_zone(self):
        raw = {"summary": "Lab", "start": {"dateTime": "2026-10-07T13:00:00Z"}, "end": {"dateTime": "2026-10-07T14:30:00Z"}}
        e = parse_event(raw, TZ)
        self.assertEqual((e["date"], e["start_time"], e["end_time"]), ("2026-10-07", "09:00", "10:30"))

    def test_all_day_end_is_exclusive(self):
        raw = {"summary": "Trip", "start": {"date": "2026-10-09"}, "end": {"date": "2026-10-12"}}
        e = parse_event(raw, TZ)
        self.assertEqual((e["date"], e["until"], e["start_time"]), ("2026-10-09", "2026-10-11", None))

    def test_cancelled_and_declined_events_dropped(self):
        self.assertIsNone(parse_event({"status": "cancelled", "start": {"date": "2026-10-09"}}, TZ))
        declined = {"summary": "x", "start": {"date": "2026-10-09"}, "end": {"date": "2026-10-10"},
                    "attendees": [{"self": True, "responseStatus": "declined"}]}
        self.assertIsNone(parse_event(declined, TZ))

    def test_task_due_is_date_only_and_completed_dropped(self):
        t = parse_task({"title": " Essay ", "due": "2026-10-09T00:00:00.000Z"}, "School")
        self.assertEqual((t["title"], t["due"]), ("Essay", "2026-10-09"))
        self.assertIsNone(parse_task({"title": "done", "status": "completed"}))


class GithubTests(unittest.TestCase):
    RAW = [
        {"name": "a", "full_name": "me/a", "owner": {"login": "Me"}, "pushed_at": "2026-10-05T12:00:00Z", "private": True, "description": "secret thing"},
        {"name": "b", "full_name": "me/b", "owner": {"login": "me"}, "pushed_at": "2026-10-06T12:00:00Z", "description": "pub"},
        {"name": "old", "full_name": "me/old", "owner": {"login": "me"}, "pushed_at": "2026-01-01T00:00:00Z"},
        {"name": "fork", "full_name": "me/fork", "owner": {"login": "me"}, "pushed_at": "2026-10-06T00:00:00Z", "fork": True},
        {"name": "theirs", "full_name": "x/theirs", "owner": {"login": "x"}, "pushed_at": "2026-10-06T00:00:00Z"},
    ]

    def test_select_active_filters_and_orders(self):
        got = select_active(self.RAW, "me", NOW, 30)
        self.assertEqual([r["name"] for r in got], ["b", "a"])

    def test_private_repo_fact_has_no_description_or_commits(self):
        priv = select_active(self.RAW, "me", NOW, 30)[1]
        fact = to_fact(priv, ["fix the secret thing"])
        self.assertEqual(set(fact), {"name", "private", "pushed"})


class RenderTests(unittest.TestCase):
    def test_today_lists_events_overdue_and_due_today(self):
        f = facts([ev("2026-10-07", loc="Room 5")], [task("Old", "2026-10-03"), task("Now", "2026-10-07")])
        out = render_brief(f, None, [])
        today = out.split("## Today")[1].split("## Rest")[0]
        self.assertIn("09:00–10:00** Lecture (Room 5)", today)
        self.assertIn("Old", today)
        self.assertIn("overdue since Sat Oct 3", today)
        self.assertIn("Now", today)

    def test_rest_of_week_stops_at_sunday_and_upcoming_starts_monday(self):
        f = facts([ev("2026-10-11", title="Sunday thing"), ev("2026-10-12", title="Monday thing")])
        out = render_brief(f, None, [])
        week = out.split("## Rest of this week")[1].split("## Upcoming")[0]
        upcoming = out.split("## Upcoming")[1]
        self.assertIn("Sunday thing", week)
        self.assertNotIn("Monday thing", week)
        self.assertIn("Monday thing", upcoming)

    def test_multi_day_event_appears_on_each_day(self):
        f = facts([ev("2026-10-08", None, None, "Trip", until="2026-10-09")])
        week = render_brief(f, None, []).split("## Rest of this week")[1].split("## Upcoming")[0]
        self.assertEqual(week.count("Trip"), 2)

    def test_every_project_listed_even_without_ai_summary(self):
        repos = [{"name": "alpha", "private": True, "pushed": "2026-10-06"},
                 {"name": "beta", "private": False, "pushed": "2026-10-05", "description": "d", "commits": ["Add thing"]}]
        out = render_brief(facts(repos=repos), {"projects": {2: "Did a thing."}}, [])
        self.assertIn("**alpha** — last push Tue Oct 6: private repo", out)
        self.assertIn("**beta** — last push Mon Oct 5: Did a thing.", out)

    def test_source_errors_are_visible(self):
        out = render_brief(facts(errors=["Google Calendar unavailable: token expired"]), None, [])
        self.assertTrue(out.startswith("> ⚠ Google Calendar unavailable"))

    def test_empty_day_says_so(self):
        out = render_brief(facts(), None, [])
        self.assertIn("Nothing scheduled and nothing due.", out)

    def test_weekly_flag_follows_setting(self):
        self.assertFalse(facts()["is_weekly"])  # Wednesday; weekly_day defaults to monday


if __name__ == "__main__":
    unittest.main()

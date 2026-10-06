import unittest

from daily_brief.config import DEFAULT_SETTINGS_NOTE, Settings, parse_settings


class ParseSettingsTests(unittest.TestCase):
    def test_default_note_parses_to_defaults_with_no_warnings(self):
        s, warnings = parse_settings(DEFAULT_SETTINGS_NOTE)
        self.assertEqual(s, Settings())
        self.assertEqual(warnings, [])

    def test_help_section_is_not_read_as_values(self):
        s, _ = parse_settings(DEFAULT_SETTINGS_NOTE)
        self.assertEqual(s.drafters, ())
        self.assertEqual(s.editor, "")

    def test_markdown_decoration_and_lists(self):
        s, w = parse_settings("- `drafters`: a/one, b/two ;c/three\n**editor**: `x/best`\nrun_time: 6:05")
        self.assertEqual(s.drafters, ("a/one", "b/two", "c/three"))
        self.assertEqual(s.editor, "x/best")
        self.assertEqual(s.run_time, "06:05")
        self.assertEqual(w, [])

    def test_bad_values_fall_back_with_warnings(self):
        s, w = parse_settings("run_time: 25:99\ntimezone: Mars/Base\nlookahead_days: 0\nweekly_day: someday")
        self.assertEqual(s, Settings())
        self.assertEqual(len(w), 4)

    def test_unknown_snake_case_key_warns_but_prose_does_not(self):
        _, w = parse_settings("lookahead_dayz: 3\nNote: hello\ntip: nothing")
        self.assertEqual(len(w), 1)
        self.assertIn("lookahead_dayz", w[0])

    def test_last_occurrence_wins(self):
        s, _ = parse_settings("lookahead_days: 3\nlookahead_days: 5")
        self.assertEqual(s.lookahead_days, 5)

    def test_repeat_shorthand_for_a_single_combo(self):
        s, w = parse_settings("drafters: Code-Strong x3\neditor: Code-Strong")
        self.assertEqual(s.drafters, ("Code-Strong",) * 3)
        self.assertEqual(w, [])
        self.assertEqual(parse_settings("drafters: a*2, b X2, c")[0].drafters, ("a", "a", "b", "b", "c"))

    def test_repeat_is_capped_and_names_with_x_digit_are_left_alone(self):
        s, w = parse_settings("drafters: Code-Strong x50, model-x2")
        self.assertEqual(s.drafters, ("Code-Strong",) * 5 + ("model-x2",))
        self.assertEqual(len(w), 1)

    def test_empty_calendars_keeps_default(self):
        s, _ = parse_settings("calendars:")
        self.assertEqual(s.calendars, ("primary",))


if __name__ == "__main__":
    unittest.main()

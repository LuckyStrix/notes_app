import tempfile
import unittest
from pathlib import Path

from daily_brief.google import GoogleError, check_client_secret


class ClientSecretCheckTests(unittest.TestCase):
    def check(self, text, encoding="utf-8"):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "client_secret.json"
            p.write_bytes(text.encode(encoding))
            check_client_secret(p)

    def test_desktop_client_json_passes_even_with_a_bom(self):
        self.check('{"installed": {"client_id": "x"}}')
        self.check('{"installed": {"client_id": "x"}}', "utf-8-sig")  # what PowerShell writes

    def test_client_id_text_gives_a_plain_error_not_extra_data(self):
        with self.assertRaisesRegex(GoogleError, "not JSON"):
            self.check("123456789012-abcdefg.apps.googleusercontent.com")

    def test_web_client_is_rejected_with_advice(self):
        with self.assertRaisesRegex(GoogleError, "Desktop app"):
            self.check('{"web": {"client_id": "x"}}')

    def test_missing_file(self):
        with self.assertRaisesRegex(GoogleError, "cannot read"):
            check_client_secret(Path("/nonexistent/client_secret.json"))


if __name__ == "__main__":
    unittest.main()

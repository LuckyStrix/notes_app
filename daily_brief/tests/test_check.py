import unittest

import requests

from daily_brief.panel import Router, RouterError


class Resp:
    def __init__(self, status=200, data=None):
        self.status_code, self._data, self.text = status, data, str(data)

    def json(self):
        return self._data


class Sess:
    def __init__(self, resp=None, exc=None):
        self.resp, self.exc, self.seen = resp, exc, None

    def get(self, url, headers=None, timeout=None):
        self.seen = (url, headers)
        if self.exc:
            raise self.exc
        return self.resp


class ModelsTests(unittest.TestCase):
    def test_lists_ids_and_sends_the_key(self):
        s = Sess(Resp(200, {"data": [{"id": "Code-Strong"}, {"id": "kr/x"}]}))
        self.assertEqual(Router("http://r/v1", "k", session=s).models(), ["Code-Strong", "kr/x"])
        self.assertEqual(s.seen, ("http://r/v1/models", {"Authorization": "Bearer k"}))

    def test_rejected_key_is_named_as_such(self):
        with self.assertRaisesRegex(RouterError, "rejected the API key"):
            Router("http://r/v1", "bad", session=Sess(Resp(401, {}))).models()

    def test_unreachable_router(self):
        with self.assertRaisesRegex(RouterError, "cannot reach"):
            Router("http://r/v1", "", session=Sess(exc=requests.ConnectionError("refused"))).models()


if __name__ == "__main__":
    unittest.main()

"""Read-only client for the notes app's REST API.

This is the ONLY way analysis_ai talks to the notes app's data, and it exposes
exactly one verb: GET. There is deliberately no post/patch/delete method, so
nothing in this package can modify the notes database through it.
"""
import json
import urllib.error
import urllib.parse
import urllib.request


class NotesAPI:
    def __init__(self, base_url: str):
        self._base = base_url.rstrip("/")

    def get(self, path: str, **params):
        query = {k: v for k, v in params.items() if v is not None}
        url = self._base + path + ("?" + urllib.parse.urlencode(query) if query else "")
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.load(resp)

    def get_or_none(self, path: str, **params):
        try:
            return self.get(path, **params)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            raise

"""Pure-logic tests -- no Ollama, Docker or notes app needed.

    cd analysis_ai && python -m unittest discover -s tests -v
"""
import inspect
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analysis_ai import chunking, extract, index, notes_api, store, sync  # noqa: E402


def _note(body, type_="text", nid="n1"):
    return {"id": nid, "type": type_, "body": body, "title": "T", "project": "P", "group_path": []}


class ReadOnlyGuarantee(unittest.TestCase):
    def test_notes_api_exposes_only_get(self):
        public = {n for n, _ in inspect.getmembers(notes_api.NotesAPI, inspect.isfunction) if not n.startswith("_")}
        self.assertEqual(public, {"get", "get_or_none"})

    def test_notes_api_never_sends_a_body_or_non_get_method(self):
        src = inspect.getsource(notes_api)
        for forbidden in ("data=", "POST", "PUT", "PATCH", "DELETE"):
            self.assertNotIn(forbidden, src)
        self.assertIn('method="GET"', src)


class FakeAPI:
    def __init__(self, notes):
        self.notes = notes

    def get(self, path, **params):
        if path == "/projects":
            return [{"id": "p1", "name": "Course", "description": None}]
        if path.endswith("/groups"):
            return []
        if path == "/notes":
            return self.notes
        raise AssertionError(path)

    def get_or_none(self, path, **params):
        return None


def _api_note(nid, body="hello"):
    return {"id": nid, "group_id": None, "type": "text", "title": nid, "body": body,
            "created_at": "2026-01-01", "updated_at": "2026-01-01"}


class SyncKeepsDeletedNotes(unittest.TestCase):
    def test_note_removed_upstream_is_flagged_not_deleted(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(store, "SNAPSHOT", Path(tmp)), mock.patch.object(store, "ensure_dirs", lambda: (Path(tmp) / "notes").mkdir(exist_ok=True)):
                sync.sync(FakeAPI([_api_note("a"), _api_note("b")]))
                result = sync.sync(FakeAPI([_api_note("a")]))  # "b" deleted in the notes app
                self.assertEqual(result["flagged_deleted_upstream"], 1)
                kept = store.read_json(Path(tmp) / "notes" / "b.json")
                self.assertEqual(kept["body"], "hello")  # content still here
                self.assertTrue(kept["deleted_upstream"])
                self.assertEqual([n["id"] for n in sync.load_notes()], ["a"])
                self.assertEqual(len(sync.load_notes(include_deleted=True)), 2)


class Chunking(unittest.TestCase):
    def test_pdf_page_markers_become_labels(self):
        body = "--- Page 1 ---\nIntro paragraph.\n\n--- Page 2 ---\nSecond page text.\n\nMore on page two."
        units = chunking.units_for(_note(body, "document"))
        self.assertEqual([u["label"] for u in units], ["p.1", "p.2", "p.2"])
        chunks = chunking.pack(units, 6000)
        self.assertEqual((chunks[0]["page_start"], chunks[0]["page_end"]), (1, 2))
        self.assertIn("[p.1] Intro paragraph.", chunks[0]["marked_text"])
        self.assertNotIn("Page 1 ---", chunks[0]["text"])

    def test_plain_note_has_no_labels(self):
        chunks = chunking.pack(chunking.units_for(_note("one\n\ntwo")), 6000)
        self.assertIsNone(chunks[0]["label_start"])
        self.assertNotIn("[", chunks[0]["marked_text"])

    def test_long_unpunctuated_text_is_split_and_nothing_is_lost(self):
        text = "word " * 2000
        units = chunking.units_for(_note(text), max_unit_chars=600)
        self.assertTrue(all(len(u["text"]) <= 600 for u in units))
        self.assertEqual("".join(u["text"] for u in units).replace(" ", ""), text.replace(" ", ""))

    def test_pack_respects_size(self):
        units = [{"text": "x" * 500, "label": None, "start": None, "page": None} for _ in range(10)]
        self.assertTrue(all(len(c["text"]) <= 1500 for c in chunking.pack(units, 1200)))

    def test_time_labels(self):
        self.assertEqual(chunking.fmt_time(75), "01:15")
        self.assertEqual(chunking.fmt_time(4399), "1:13:19")


class ExtractionMerge(unittest.TestCase):
    def _chunk(self, marked, label):
        return {"label_start": label, "marked_text": marked}

    def test_invented_timestamp_is_replaced_by_real_marker(self):
        chunk = self._chunk("[12:00] alpha\n[12:45] beta", "12:00")
        part = {"topics": [{"name": "A", "explanation": "e", "at": "00:00"},
                           {"name": "B", "explanation": "e", "at": "[12:45]"}]}
        merged = extract._merge([part], [chunk])
        self.assertEqual([t["at"] for t in merged["topics"]], ["12:00", "12:45"])

    def test_notes_without_markers_get_no_timestamp(self):
        merged = extract._merge([{"topics": [{"name": "A", "explanation": "e", "at": "00:00"}]}], [self._chunk("plain", None)])
        self.assertIsNone(merged["topics"][0]["at"])

    def test_duplicate_terms_keep_the_fuller_definition(self):
        chunks = [self._chunk("a", None), self._chunk("b", None)]
        parts = [{"key_terms": [{"term": "PPF", "definition": "short"}]},
                 {"key_terms": [{"term": "ppf", "definition": "a much longer definition"}]}]
        merged = extract._merge(parts, chunks)
        self.assertEqual(len(merged["key_terms"]), 1)
        self.assertEqual(merged["key_terms"][0]["definition"], "a much longer definition")

    def test_cache_key_changes_with_model_and_text(self):
        base = extract.source_hash("text", "m1")
        self.assertNotEqual(base, extract.source_hash("text", "m2"))
        self.assertNotEqual(base, extract.source_hash("text2", "m1"))
        self.assertEqual(base, extract.source_hash("text", "m1"))


class Search(unittest.TestCase):
    def test_fts_query_is_safe_and_drops_noise(self):
        self.assertEqual(index._fts_query("What's the R/W ratio?"), '"What" OR "the" OR "ratio"')
        self.assertIsNone(index._fts_query("?? !"))


class AtomicWrite(unittest.TestCase):
    def test_write_json_leaves_no_temp_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.json"
            store.write_json(path, {"a": 1})
            self.assertEqual(store.read_json(path), {"a": 1})
            self.assertEqual([p.name for p in Path(tmp).iterdir()], ["x.json"])


if __name__ == "__main__":
    unittest.main()

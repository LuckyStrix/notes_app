"""Job queue, settings validation and HTTP guard tests -- no Ollama/Docker/GPU needed.

    cd analysis_ai && python -m unittest discover -s tests -v
"""
import json
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analysis_ai import config, jobs, store  # noqa: E402


def wait_for(cond, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


class JobQueue(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch.object(jobs, "JOBS_FILE", Path(self.tmp.name) / "jobs.json")
        patcher.start()
        self.addCleanup(patcher.stop)

    def status(self, mgr, job_id):
        return mgr.get(job_id)["status"]

    def test_runs_jobs_one_at_a_time_and_dedupes_identical_requests(self):
        running, peak, gate = [0], [0], threading.Event()

        def runner(kind, params, ctx):
            running[0] += 1
            peak[0] = max(peak[0], running[0])
            gate.wait(2)
            running[0] -= 1

        mgr = jobs.JobManager(runner)
        a = mgr.submit("index", "a", {"x": 1})
        again = mgr.submit("index", "a", {"x": 1})
        b = mgr.submit("index", "b", {"x": 2})
        self.assertEqual(a["id"], again["id"])
        gate.set()
        self.assertTrue(wait_for(lambda: self.status(mgr, b["id"]) == "done"))
        self.assertEqual(peak[0], 1)  # never two at once: they'd fight over the GPU

    def test_running_job_can_be_cancelled_at_its_next_checkpoint(self):
        def runner(kind, params, ctx):
            for i in range(1000):
                ctx.check()
                ctx.progress(i, 1000, "working")
                time.sleep(0.01)

        mgr = jobs.JobManager(runner)
        job = mgr.submit("extract", "long", {})
        self.assertTrue(wait_for(lambda: self.status(mgr, job["id"]) == "running"))
        mgr.cancel(job["id"])
        self.assertTrue(wait_for(lambda: self.status(mgr, job["id"]) == "cancelled"))

    def test_queued_job_cancels_immediately_without_running(self):
        gate, ran = threading.Event(), []

        def runner(kind, params, ctx):
            ran.append(params["n"])
            gate.wait(2)

        mgr = jobs.JobManager(runner)
        first = mgr.submit("index", "first", {"n": 1})
        second = mgr.submit("index", "second", {"n": 2})
        self.assertTrue(wait_for(lambda: self.status(mgr, first["id"]) == "running"))
        mgr.cancel(second["id"])
        gate.set()
        self.assertTrue(wait_for(lambda: self.status(mgr, first["id"]) == "done"))
        time.sleep(0.2)
        self.assertEqual(ran, [1])
        self.assertEqual(self.status(mgr, second["id"]), "cancelled")

    def test_failed_job_is_recorded_and_does_not_stop_the_queue(self):
        def runner(kind, params, ctx):
            if params.get("boom"):
                raise RuntimeError("model exploded")

        mgr = jobs.JobManager(runner)
        bad = mgr.submit("index", "bad", {"boom": True})
        good = mgr.submit("index", "good", {"boom": False})
        self.assertTrue(wait_for(lambda: self.status(mgr, good["id"]) == "done"))
        self.assertEqual(mgr.get(bad["id"])["status"], "failed")
        self.assertIn("model exploded", mgr.get(bad["id"])["error"])

    def test_job_running_at_shutdown_comes_back_interrupted_not_resumed(self):
        (Path(self.tmp.name) / "jobs.json").write_text(json.dumps([
            {"id": "old", "kind": "transcribe", "title": "t", "params": {}, "status": "running", "created": "x",
             "started": "x", "finished": None, "progress": {"done": 0, "total": 0, "current": ""}, "log": [], "error": None}]))
        ran = []
        mgr = jobs.JobManager(lambda *a: ran.append(a))
        time.sleep(0.2)
        self.assertEqual(mgr.get("old")["status"], "interrupted")
        self.assertEqual(ran, [])  # a GPU job never restarts by itself


class SettingsValidation(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch.object(config, "DATA_DIR", Path(self.tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_only_whitelisted_settings_can_change(self):
        for bad in ({"ollama_url": "http://evil"}, {"uploads_dir": "/"}, {"notes_api_url": "http://x"}, {"docker_image": "x"}):
            with self.assertRaises(ValueError):
                config.save_editable(bad)
        self.assertFalse((Path(self.tmp.name) / "config.json").exists())

    def test_values_are_validated(self):
        for bad in ({"whisper_model": "../../etc"}, {"whisper_language": "English"}, {"retrieval_top_k": 0},
                    {"retrieval_top_k": True}, {"sync_interval_seconds": 5}, {"auto_sync": "yes"},
                    {"models": {"extract": ""}}, {"models": {"bogus": "x"}}):
            with self.assertRaises(ValueError, msg=bad):
                config.save_editable(bad)

    def test_valid_update_persists_and_merges(self):
        cfg = config.save_editable({"models": {"chat": "gpt-oss:20b"}, "whisper_model": "medium"})
        self.assertEqual(cfg["models"]["chat"], "gpt-oss:20b")
        self.assertEqual(cfg["models"]["extract"], config.DEFAULTS["models"]["extract"])  # untouched
        cfg = config.save_editable({"retrieval_top_k": 12})
        self.assertEqual((cfg["whisper_model"], cfg["retrieval_top_k"]), ("medium", 12))  # earlier edit kept


class ModelDefaults(unittest.TestCase):
    def test_primary_model_and_context_are_sized_for_a_16gb_gpu(self):
        d = config.DEFAULTS
        self.assertTrue(d["models"]["extract"].endswith("Q3_K_M"))
        self.assertEqual(d["models"]["extract"], d["models"]["chat"])  # one resident model, no swapping
        self.assertLessEqual(d["num_ctx"]["extract"], 8192)
        self.assertLessEqual(d["num_ctx"]["chat"], 16384)

    def test_thinking_is_off_for_qwen_models_and_explicit_config_wins(self):
        from analysis_ai import ollama
        cfg = config.load()
        self.assertIs(ollama.think_setting(cfg, cfg["models"]["extract"]), False)
        self.assertIs(ollama.think_setting(cfg, "some-other-qwen3:14b"), False)  # a model picked later in Settings
        self.assertEqual(ollama.think_setting(cfg, "gpt-oss:20b"), "low")
        self.assertIsNone(ollama.think_setting(cfg, "llama3.1:8b"))  # non-thinking models: leave alone
        body = ollama._body(cfg, "extract", [], stream=False, temperature=0.2)
        self.assertIs(body["think"], False)
        self.assertEqual(body["options"]["num_ctx"], cfg["num_ctx"]["extract"])


class OllamaTuning(unittest.TestCase):
    def test_per_model_options_reach_the_request_only_for_that_model(self):
        from analysis_ai import ollama
        cfg = config.load()
        primary = ollama._body(cfg, "extract", [], stream=False, temperature=0.2)["options"]
        self.assertEqual((primary["num_gpu"], primary["num_thread"]), (99, 4))
        cfg["models"]["extract"] = "llama3.1:8b"  # a model picked later in Settings: no forced offload
        other = ollama._body(cfg, "extract", [], stream=False, temperature=0.2)["options"]
        self.assertNotIn("num_gpu", other)
        self.assertNotIn("num_thread", other)

    def test_forced_offload_is_dropped_on_retry_instead_of_failing_the_job(self):
        from analysis_ai import ollama
        sent = []

        def fake_post(cfg, path, body, **kw):
            sent.append(dict(body["options"]))
            if len(sent) == 1:
                raise urllib.error.HTTPError("x", 500, "cannot allocate VRAM", {}, None)
            import io
            return io.BytesIO(json.dumps({"message": {"content": "{\"ok\": true}"}}).encode())

        with mock.patch.object(ollama, "_post", fake_post), mock.patch.object(ollama.time, "sleep", lambda s: None):
            self.assertEqual(ollama.generate_json(config.load(), "extract", "p", {}), {"ok": True})
        self.assertIn("num_gpu", sent[0])
        self.assertNotIn("num_gpu", sent[1])  # retried without forcing full offload
        self.assertEqual(sent[1]["num_thread"], 4)  # thread cap still applies


class HttpGuards(unittest.TestCase):
    """Uses the real ASGI app with the job runner and sync loop stubbed out."""

    @classmethod
    def setUpClass(cls):
        try:
            from starlette.testclient import TestClient
        except ImportError:
            raise unittest.SkipTest("starlette/httpx not installed")
        from analysis_ai import server
        cls.server = server
        cls.tmp = tempfile.TemporaryDirectory()
        cls.patches = [
            mock.patch.object(jobs, "JOBS_FILE", Path(cls.tmp.name) / "jobs.json"),
            mock.patch.object(server, "_sync_loop", lambda: None),
            mock.patch.object(server.pipeline, "run", lambda *a: None),
        ]
        for p in cls.patches:
            p.start()
        cls.client = TestClient(server.app)
        cls.client.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)
        for p in cls.patches:
            p.stop()
        cls.tmp.cleanup()

    def test_state_changing_requests_must_be_json(self):
        for method, path in (("post", "/api/sync"), ("post", "/api/jobs"), ("put", "/api/settings"), ("post", "/api/chat")):
            r = getattr(self.client, method)(path, content=b"{}", headers={"Content-Type": "text/plain"})
            self.assertEqual(r.status_code, 415, path)

    def test_ids_are_validated_before_touching_the_filesystem(self):
        self.assertEqual(self.client.get("/api/notes/..%2F..%2Fconfig").status_code, 404)
        self.assertEqual(self.client.get("/api/notes/not-a-uuid").status_code, 404)
        self.assertEqual(self.client.get("/api/projects/x/library").status_code, 404)

    def test_job_requests_are_validated(self):
        post = lambda body: self.client.post("/api/jobs", json=body).status_code  # noqa: E731
        self.assertEqual(post({"kind": "format-c-drive"}), 400)
        self.assertEqual(post({"kind": "update"}), 400)  # needs a project
        self.assertEqual(post({"kind": "extract", "ids": ["00000000-0000-0000-0000-000000000000"]}), 400)

    def test_settings_endpoint_refuses_deployment_settings(self):
        r = self.client.put("/api/settings", json={"ollama_url": "http://evil"})
        self.assertEqual(r.status_code, 400)

    def test_ping_and_index_page(self):
        self.assertEqual(self.client.get("/api/ping").json()["ok"], True)
        self.assertIn("Analysis", self.client.get("/").text)


if __name__ == "__main__":
    unittest.main()

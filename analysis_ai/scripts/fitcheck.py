"""Does each model fit entirely in VRAM at a given context size?

Loads each model with a one-token generation at each context size, reads how much
of it Ollama placed on the GPU (/api/ps), then unloads it. No notes are read.

    python fitcheck.py 8192,16384 model1 [model2 ...]
"""
import json
import sys
import urllib.request

OLLAMA = "http://localhost:11434"


def post(path, body, timeout=900):
    req = urllib.request.Request(f"{OLLAMA}{path}", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def main() -> int:
    contexts = [int(c) for c in sys.argv[1].split(",")]
    print(f"{'model':70} {'ctx':>6} {'total GB':>9} {'on GPU':>8}")
    for model in sys.argv[2:]:
        for ctx in contexts:
            try:
                post("/api/generate", {"model": model, "prompt": "Hi", "stream": False, "keep_alive": "1m",
                                       "options": {"num_ctx": ctx, "num_predict": 1}})
                with urllib.request.urlopen(f"{OLLAMA}/api/ps", timeout=10) as resp:
                    loaded = [m for m in json.load(resp)["models"] if model in (m["name"], m["model"])]
                m = loaded[0]
                print(f"{model:70} {ctx:>6} {m['size'] / 1e9:>9.1f} {100 * m['size_vram'] / m['size']:>7.0f}%", flush=True)
            except Exception as exc:  # noqa: BLE001 -- report and continue
                print(f"{model:70} {ctx:>6}  FAILED: {exc}", flush=True)
            finally:
                try:
                    post("/api/generate", {"model": model, "keep_alive": 0}, timeout=60)
                except OSError:
                    pass
    return 0


if __name__ == "__main__":
    sys.exit(main())

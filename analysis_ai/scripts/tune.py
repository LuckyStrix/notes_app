"""Measure what num_gpu / num_thread do to GPU placement, speed and CPU use.

For each variant: unload the model, load it with those options, then time one real
generation and record (a) how much of the model Ollama put on the GPU, (b) tokens/sec,
(c) how many CPU cores the llama-server runner burned while generating.

Host-side dev tool (needs `pip install psutil`); reads one lecture transcript, writes nothing.

    python tune.py <model> <transcript.json> [ctx]
"""
import json
import sys
import time
import urllib.request

import psutil

OLLAMA = "http://localhost:11434"

VARIANTS = {
    "Ollama automatic": {},
    "num_thread=4": {"num_thread": 4},
    "num_gpu=99": {"num_gpu": 99},
    "num_gpu=99 + num_thread=4": {"num_gpu": 99, "num_thread": 4},
}


def post(path, body, timeout=1200):
    req = urllib.request.Request(f"{OLLAMA}{path}", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def ps_entry(model):
    with urllib.request.urlopen(f"{OLLAMA}/api/ps", timeout=10) as resp:
        return next((m for m in json.load(resp)["models"] if model in (m["name"], m["model"])), None)


def unload(model):
    post("/api/generate", {"model": model, "keep_alive": 0}, timeout=60)
    for _ in range(40):
        if ps_entry(model) is None:
            return
        time.sleep(0.5)


def runner_procs():
    serve = [p for p in psutil.process_iter(["name", "cmdline"])
             if (p.info["name"] or "").lower().startswith("ollama") and "serve" in (p.info["cmdline"] or [])]
    procs = []
    for s in serve:
        procs += s.children(recursive=True)
    return procs


def cpu_seconds(procs):
    total = 0.0
    for p in procs:
        try:
            t = p.cpu_times()
            total += t.user + t.system
        except psutil.Error:
            pass
    return total


def main() -> int:
    model, transcript_path = sys.argv[1], sys.argv[2]
    ctx = int(sys.argv[3]) if len(sys.argv) > 3 else 8192
    text = json.load(open(transcript_path, encoding="utf-8"))["full_text"][20000:26000]
    prompt = "Summarise the key economic ideas in this lecture excerpt as a bullet list:\n\n" + text
    logical = psutil.cpu_count()
    print(f"model {model} | ctx {ctx} | {logical} logical CPUs | prompt {len(prompt)} chars\n")
    print(f"{'variant':30} {'GPU':>5} {'size GB':>8} {'gen tok/s':>10} {'CPU cores':>10} {'% of CPU':>9}")

    for name, extra in VARIANTS.items():
        unload(model)
        options = {"num_ctx": ctx, "temperature": 0.2, "seed": 1, **extra}
        post("/api/generate", {"model": model, "prompt": "Hi", "stream": False, "keep_alive": "5m",
                               "options": {**options, "num_predict": 1}})            # load + warm up
        entry = ps_entry(model)
        gpu = 100 * entry["size_vram"] / entry["size"]
        procs = runner_procs()
        time.sleep(1)
        c0, t0 = cpu_seconds(procs), time.time()
        resp = post("/api/chat", {"model": model, "messages": [{"role": "user", "content": prompt}], "stream": False,
                                  "think": False, "keep_alive": "5m", "options": {**options, "num_predict": 300}})
        wall = time.time() - t0
        cores = (cpu_seconds(procs) - c0) / wall
        tps = resp["eval_count"] / (resp["eval_duration"] / 1e9)
        print(f"{name:30} {gpu:>4.0f}% {entry['size'] / 1e9:>8.1f} {tps:>10.1f} {cores:>10.1f} {100 * cores / logical:>8.0f}%", flush=True)
    unload(model)
    return 0


if __name__ == "__main__":
    sys.exit(main())

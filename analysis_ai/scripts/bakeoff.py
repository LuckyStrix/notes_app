"""Run the same lecture transcript through several Ollama models and save the
study cards side by side, so model choice is made on evidence.

Reads a transcript JSON (from transcribe.py), writes only under the output
directory. Talks to Ollama over HTTP; standard library only.

    python bakeoff.py <transcript.json> <out_dir> model1 [model2 ...]
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

OLLAMA = "http://localhost:11434"
# BAKEOFF_CTX lowers the context window: a smaller KV cache leaves room for more of
# the model on the GPU. The whole-lecture prompt here is ~10.5K tokens, so >= 14000.
NUM_CTX = int(os.environ.get("BAKEOFF_CTX", 32768))

# Thinking-capable models need an explicit setting. gpt-oss can't disable
# thinking (only low/medium/high); qwen3.x can, and combining its thinking with
# grammar-constrained JSON output is flaky, so it is turned off here.
THINK = {"gpt-oss:20b": "low", "qwen3.6:27b": False}

STUDY_CARD_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "Short descriptive title of what this lecture covered"},
        "summary": {"type": "string", "description": "5-8 sentence summary of the substantive content"},
        "topics": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "explanation": {"type": "string", "description": "2-4 sentences, in the lecturer's framing"},
                    "timestamp": {"type": "string", "description": "mm:ss where this begins"},
                },
                "required": ["name", "explanation", "timestamp"],
            },
        },
        "key_terms": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"term": {"type": "string"}, "definition": {"type": "string"}},
                "required": ["term", "definition"],
            },
        },
        "formulas_and_rules": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"statement": {"type": "string"}, "context": {"type": "string"}},
                "required": ["statement", "context"],
            },
        },
        "examples": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"description": {"type": "string"}, "takeaway": {"type": "string"}},
                "required": ["description", "takeaway"],
            },
        },
        "logistics": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Exams, deadlines, assignments, readings mentioned",
        },
    },
    "required": ["title", "summary", "topics", "key_terms", "formulas_and_rules", "examples", "logistics"],
}

PROMPT = """You are turning a raw, auto-generated lecture transcript into a study card for the student who attended it.

Rules:
- Extract only substantive course content. Ignore small talk, jokes, personal anecdotes, tangents unrelated to the course, and classroom management chatter -- except exams, deadlines, assignments and readings, which go in "logistics".
- The transcript is auto-generated and may contain misheard words. Use the surrounding context to interpret them, but do not invent facts, numbers or terms that the lecture does not support.
- Be specific: prefer the lecturer's actual definitions, numbers, and examples over generic textbook statements.
- Every topic needs the [mm:ss] timestamp of where it begins, taken from the markers in the transcript.
- If a section has nothing in it, return an empty list rather than filling it with guesses.

TRANSCRIPT (with [mm:ss] markers):
{transcript}
"""


def fmt_time(seconds: float) -> str:
    return f"{int(seconds) // 60:02d}:{int(seconds) % 60:02d}"


def timestamped_transcript(segments: list[dict], block_seconds: float = 45.0) -> str:
    """Group segments into ~45s blocks, each prefixed with its start time."""
    blocks, current, block_start = [], [], None
    for seg in segments:
        if block_start is None:
            block_start = seg["start"]
        current.append(seg["text"])
        if seg["end"] - block_start >= block_seconds:
            blocks.append(f"[{fmt_time(block_start)}] {' '.join(current)}")
            current, block_start = [], None
    if current:
        blocks.append(f"[{fmt_time(block_start)}] {' '.join(current)}")
    return "\n".join(blocks)


def _post(path: str, body: dict, timeout: int = 3600) -> dict:
    req = urllib.request.Request(
        f"{OLLAMA}{path}", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def gpu_share(model: str) -> float | None:
    """Fraction of the loaded model that is in VRAM, from Ollama's /api/ps."""
    with urllib.request.urlopen(f"{OLLAMA}/api/ps", timeout=10) as resp:
        for m in json.load(resp).get("models", []):
            if m["name"] == model or m["model"] == model:
                return round(100 * m["size_vram"] / m["size"], 1) if m["size"] else None
    return None


def call_ollama(spec: str, prompt: str) -> tuple[dict, float | None]:
    """`spec` is a model name, optionally with a thinking effort: `gpt-oss:20b@high`.
    Returns (response, percent of the model that was on the GPU)."""
    model, _, effort = spec.partition("@")
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "format": STUDY_CARD_SCHEMA,
        "stream": False,
        "options": {"num_ctx": NUM_CTX, "temperature": 0.2},
        "keep_alive": "2m",  # long enough to read GPU placement afterwards; unloaded explicitly below
    }
    think = effort or THINK.get(model)
    if think is None and "qwen" in model.lower():
        think = False  # community Qwen builds: keep thinking off, as for the official one
    if think is not None:
        body["think"] = think
    try:
        try:
            resp = _post("/api/chat", body)
        except urllib.error.HTTPError as exc:
            if exc.code != 400 or "think" not in body:
                raise
            print(f"  (model rejected the think setting, retrying without: {exc.read().decode()[:120]})", flush=True)
            del body["think"]
            resp = _post("/api/chat", body)
        return resp, gpu_share(model)
    finally:
        try:
            _post("/api/generate", {"model": model, "keep_alive": 0}, timeout=60)  # free VRAM for the next model
        except OSError:
            pass


def grounding(card: dict, transcript_text: str) -> dict:
    """Crude hallucination check: what fraction of extracted key terms / formula
    words actually occur in the transcript? Misheard terms will lower this a
    little for every model equally; big gaps between models are the signal."""
    haystack = transcript_text.lower()

    def present(text: str) -> bool:
        words = [w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 3]
        return not words or sum(w in haystack for w in words) / len(words) >= 0.5

    terms = [t["term"] for t in card.get("key_terms", [])]
    return {
        "key_terms": len(terms),
        "key_terms_grounded": sum(present(t) for t in terms),
        "topics": len(card.get("topics", [])),
        "formulas": len(card.get("formulas_and_rules", [])),
        "examples": len(card.get("examples", [])),
        "logistics": len(card.get("logistics", [])),
    }


def render_markdown(card: dict) -> str:
    out = [f"# {card.get('title', '')}", "", card.get("summary", ""), "", "## Topics"]
    for t in card.get("topics", []):
        # Models often echo the prompt's "[mm:ss]" brackets back inside the value.
        out += [f"- **{t['name']}** [{t['timestamp'].strip('[] ')}] -- {t['explanation']}"]
    out += ["", "## Key terms"] + [f"- **{t['term']}**: {t['definition']}" for t in card.get("key_terms", [])]
    out += ["", "## Formulas and rules"] + [f"- {f['statement']} ({f['context']})" for f in card.get("formulas_and_rules", [])]
    out += ["", "## Examples"] + [f"- {e['description']} -> {e['takeaway']}" for e in card.get("examples", [])]
    out += ["", "## Logistics"] + [f"- {l}" for l in card.get("logistics", [])]
    return "\n".join(out) + "\n"


def main() -> int:
    transcript_path, out_dir, models = sys.argv[1], sys.argv[2], sys.argv[3:]
    import os

    os.makedirs(out_dir, exist_ok=True)
    with open(transcript_path, encoding="utf-8") as fh:
        transcript = json.load(fh)
    prompt = PROMPT.format(transcript=timestamped_transcript(transcript["segments"]))
    print(f"prompt: {len(prompt)} chars", flush=True)

    all_metrics = {}
    for model in models:
        slug = model.replace(":", "_").replace("/", "_")
        print(f"\n=== {model}", flush=True)
        started = time.time()
        try:
            resp, on_gpu = call_ollama(model, prompt)
        except Exception as exc:  # noqa: BLE001 -- record and move on to the next model
            print(f"  FAILED: {exc}", flush=True)
            all_metrics[model] = {"error": str(exc)}
            continue
        elapsed = time.time() - started
        raw = resp["message"]["content"]
        with open(f"{out_dir}/{slug}.raw.txt", "w", encoding="utf-8") as fh:
            fh.write(raw)
        metrics = {
            "seconds": round(elapsed),
            "prompt_tokens": resp.get("prompt_eval_count"),
            "output_tokens": resp.get("eval_count"),
            "tokens_per_sec": round(resp["eval_count"] / (resp["eval_duration"] / 1e9), 1) if resp.get("eval_duration") else None,
            "percent_on_gpu": on_gpu,
            "num_ctx": NUM_CTX,
        }
        try:
            card = json.loads(raw)
        except json.JSONDecodeError as exc:
            metrics["error"] = f"invalid JSON: {exc}"
            all_metrics[model] = metrics
            print(f"  {metrics}", flush=True)
            continue
        metrics.update(grounding(card, transcript["full_text"]))
        with open(f"{out_dir}/{slug}.card.json", "w", encoding="utf-8") as fh:
            json.dump(card, fh, ensure_ascii=False, indent=1)
        with open(f"{out_dir}/{slug}.card.md", "w", encoding="utf-8") as fh:
            fh.write(render_markdown(card))
        all_metrics[model] = metrics
        print(f"  {metrics}", flush=True)

    with open(f"{out_dir}/metrics.json", "w", encoding="utf-8") as fh:
        json.dump(all_metrics, fh, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())

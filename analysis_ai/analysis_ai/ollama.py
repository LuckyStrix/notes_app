"""Minimal Ollama client (standard library only): JSON-constrained generation,
streaming chat, and embeddings. Each call takes a *stage* name ("extract",
"chat") so the model and context size come from config, per stage."""
import json
import time
import urllib.error
import urllib.request
from collections.abc import Iterator


def _body(cfg: dict, stage: str, messages: list[dict], *, stream: bool, temperature: float, schema=None,
          num_predict: int | None = None, keep_alive: str = "10m") -> dict:
    model = cfg["models"][stage]
    options = {"num_ctx": cfg["num_ctx"][stage], "temperature": temperature}
    # Per-model tuning (num_gpu / num_thread), e.g. to stop a single CPU-resident layer from
    # keeping every llama-server thread spinning. See config.py.
    options.update(cfg.get("model_options", {}).get(model, {}))
    if num_predict:
        options["num_predict"] = num_predict
    body = {"model": model, "messages": messages, "stream": stream, "options": options, "keep_alive": keep_alive}
    if schema is not None:
        body["format"] = schema
    think = think_setting(cfg, model)
    if think is not None:
        body["think"] = think
    return body


def think_setting(cfg: dict, model: str):
    """The `think` value to send for this model, or None to leave it at the model's default.
    Explicit config wins; otherwise Qwen models get thinking OFF, because thinking combined with
    schema-constrained output can run away until the context is full and return nothing."""
    configured = cfg.get("think", {})
    if model in configured:
        return configured[model]
    return False if "qwen" in model.lower() else None


def _post(cfg: dict, path: str, body: dict, *, timeout: int = 3600):
    req = urllib.request.Request(
        cfg["ollama_url"].rstrip("/") + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}
    )
    return urllib.request.urlopen(req, timeout=timeout)


def generate_json(cfg: dict, stage: str, prompt: str, schema: dict, *, temperature: float = 0.2,
                  num_predict: int = 4096, attempts: int = 3) -> dict:
    """One schema-constrained completion, parsed. Retries on transport errors or
    unparseable output (e.g. a generation cut off by num_predict)."""
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            body = _body(cfg, stage, [{"role": "user", "content": prompt}], stream=False,
                         temperature=temperature, schema=schema, num_predict=num_predict)
            if attempt > 0:
                # Forcing every layer onto the GPU can fail if another app has taken VRAM.
                # After a failure, let Ollama decide the split instead of failing the job.
                body["options"].pop("num_gpu", None)
            with _post(cfg, "/api/chat", body) as resp:
                content = json.load(resp)["message"]["content"]
            return json.loads(content)
        except (json.JSONDecodeError, OSError, KeyError) as exc:
            last = exc
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"Ollama JSON generation failed after {attempts} attempts: {last}")


def chat_stream(cfg: dict, stage: str, messages: list[dict], *, temperature: float = 0.3) -> Iterator[str]:
    body = _body(cfg, stage, messages, stream=True, temperature=temperature, keep_alive="30m")
    try:
        resp = _post(cfg, "/api/chat", body)
    except urllib.error.HTTPError:
        if "num_gpu" not in body["options"]:
            raise
        del body["options"]["num_gpu"]  # forced full offload was refused; let Ollama choose
        resp = _post(cfg, "/api/chat", body)
    with resp:
        for line in resp:
            if not line.strip():
                continue
            chunk = json.loads(line)
            piece = chunk.get("message", {}).get("content", "")
            if piece:
                yield piece
            if chunk.get("done"):
                break


def embed(cfg: dict, texts: list[str], *, batch: int = 32, on_batch=None) -> list[list[float]]:
    out: list[list[float]] = []
    for i in range(0, len(texts), batch):
        if on_batch:
            on_batch()
        body = {"model": cfg["models"]["embed"], "input": texts[i : i + batch], "keep_alive": "10m"}
        with _post(cfg, "/api/embed", body, timeout=600) as resp:
            out.extend(json.load(resp)["embeddings"])
    return out


def list_models(cfg: dict) -> list[dict]:
    with urllib.request.urlopen(cfg["ollama_url"].rstrip("/") + "/api/tags", timeout=10) as resp:
        return json.load(resp)["models"]


def unload_all(cfg: dict) -> None:
    """Ask Ollama to drop every resident model. Called before Whisper starts so the
    two never fight over VRAM (Ollama otherwise keeps a model loaded for minutes)."""
    try:
        with urllib.request.urlopen(cfg["ollama_url"].rstrip("/") + "/api/ps", timeout=10) as resp:
            loaded = [m["model"] for m in json.load(resp).get("models", [])]
        for model in loaded:
            with _post(cfg, "/api/generate", {"model": model, "keep_alive": 0}, timeout=60):
                pass
    except OSError:
        pass  # Ollama not running -> nothing to unload

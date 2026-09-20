"""Settings, with defaults overridable via data/config.json (or AAI_DATA_DIR for the data location)."""
import json
import os
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent.parent  # .../analysis_ai
REPO_ROOT = PACKAGE_ROOT.parent
DATA_DIR = Path(os.environ.get("AAI_DATA_DIR", PACKAGE_ROOT / "data"))

DEFAULTS = {
    "notes_api_url": "http://localhost:8000",
    "ollama_url": "http://localhost:11434",
    # Host path of the notes app's uploads folder. Only ever mounted read-only.
    "uploads_dir": str(REPO_ROOT / "uploads"),
    "docker_image": "notes_app-worker:latest",
    "whisper_model": "large-v3",
    # Explicit on purpose: Whisper's auto-detect labelled English lectures as Welsh.
    "whisper_language": "en",
    # Model per stage. Qwen3.6 27B at Q3_K_M (13.6 GB) is the best fit for a 16 GB GPU found in
    # the bake-offs (see README): ~94% on the GPU and about twice the speed of the Q4_K_M build,
    # which only ~78% fits, with the same exam facts extracted.
    "models": {"extract": "hf.co/unsloth/Qwen3.6-27B-GGUF:Q3_K_M", "chat": "hf.co/unsloth/Qwen3.6-27B-GGUF:Q3_K_M",
               "embed": "nomic-embed-text"},
    # Context windows are chosen for VRAM, not convenience: every extra 8k of context costs
    # roughly 0.5 GB, and a model that spills onto the CPU is far slower. Card-building chunks
    # are ~2K tokens in + <=4K out, so 8k is plenty; chat carries the class overview + passages.
    "num_ctx": {"extract": 8192, "chat": 16384},
    # Ollama "think" setting per model. Models not listed use their own default, except Qwen
    # models, which ollama.py turns thinking off for (thinking + JSON schema output is unreliable).
    "think": {"gpt-oss:20b": "low", "qwen3.6:27b": False, "hf.co/unsloth/Qwen3.6-27B-GGUF:Q3_K_M": False},
    # Extra Ollama request options per model. Ollama's automatic fit loaded this model as 64/65
    # layers on the GPU, leaving ~2 GB of VRAM free, and the one layer on the CPU kept all 10
    # llama-server threads busy-waiting (~40% CPU). num_gpu=99 = "put every layer on the GPU";
    # num_thread=4 caps the threads, since with the model on the GPU the CPU has almost nothing
    # to compute. (If forcing full offload is refused, ollama.py retries without num_gpu.)
    "model_options": {"hf.co/unsloth/Qwen3.6-27B-GGUF:Q3_K_M": {"num_gpu": 99, "num_thread": 4}},
    # Notes with more text than this (e.g. a whole textbook) are indexed for
    # search only, not summarized by the LLM.
    "max_extract_chars": 150_000,
    "transcript_chunk_seconds": 600,
    "text_chunk_chars": 6000,
    # Retrieval for chat.
    "retrieval_chunk_chars": 1200,
    "retrieval_top_k": 8,
    # Web service.
    "auto_sync": True,
    "sync_interval_seconds": 120,
    # "auto": run Whisper in a throwaway docker container when docker is on PATH,
    # or directly when running inside the analysis_ai container.
    "transcribe_mode": "auto",
}

# Deployment-specific values come from the environment (see docker-compose.yml).
ENV_OVERRIDES = {
    "AAI_NOTES_API_URL": "notes_api_url",
    "AAI_OLLAMA_URL": "ollama_url",
    "AAI_UPLOADS_DIR": "uploads_dir",
}
# Settings the web UI may change. Everything else (URLs, paths, image) is deployment config.
EDITABLE = {
    "models": {"extract": str, "chat": str, "embed": str},
    "whisper_model": str,
    "whisper_language": str,
    "auto_sync": bool,
    "sync_interval_seconds": int,
    "retrieval_top_k": int,
    "max_extract_chars": int,
}


def _merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in override.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def load() -> dict:
    cfg_file = DATA_DIR / "config.json"
    cfg = _merge(DEFAULTS, json.loads(cfg_file.read_text(encoding="utf-8"))) if cfg_file.exists() else _merge(DEFAULTS, {})
    for env, key in ENV_OVERRIDES.items():
        if os.environ.get(env):
            cfg[key] = os.environ[env]
    return cfg


WHISPER_MODELS = ["tiny", "base", "small", "medium", "large-v3", "distil-large-v3"]


def save_editable(updates: dict) -> dict:
    """Validate and persist UI-changeable settings into data/config.json (atomic).
    Anything not in EDITABLE is rejected, so the web UI can never repoint the tool
    at a different notes API, Ollama host, or filesystem path."""
    unknown = set(updates) - set(EDITABLE)
    if unknown:
        raise ValueError(f"not editable: {', '.join(sorted(unknown))}")
    cfg_file = DATA_DIR / "config.json"
    current = json.loads(cfg_file.read_text(encoding="utf-8")) if cfg_file.exists() else {}

    def text(v, what):
        if not isinstance(v, str) or not v.strip() or len(v) > 100 or any(ord(c) < 32 for c in v):
            raise ValueError(f"{what} must be a short non-empty string")
        return v.strip()

    def number(v, what, lo, hi):
        if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
            raise ValueError(f"{what} must be an integer between {lo} and {hi}")
        return v

    for key, value in updates.items():
        if key == "models":
            if not isinstance(value, dict) or set(value) - set(EDITABLE["models"]):
                raise ValueError("models must map extract/chat/embed to model names")
            current.setdefault("models", {}).update({k: text(v, f"models.{k}") for k, v in value.items()})
        elif key == "whisper_model":
            if value not in WHISPER_MODELS:
                raise ValueError(f"whisper_model must be one of {WHISPER_MODELS}")
            current[key] = value
        elif key == "whisper_language":
            if not isinstance(value, str) or not value.isalpha() or not 2 <= len(value) <= 3 or not value.islower():
                raise ValueError("whisper_language must be a 2-3 letter lowercase code, e.g. en")
            current[key] = value
        elif key == "auto_sync":
            if not isinstance(value, bool):
                raise ValueError("auto_sync must be true or false")
            current[key] = value
        elif key == "sync_interval_seconds":
            current[key] = number(value, key, 30, 86400)
        elif key == "retrieval_top_k":
            current[key] = number(value, key, 1, 40)
        elif key == "max_extract_chars":
            current[key] = number(value, key, 10_000, 5_000_000)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = cfg_file.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(current, indent=1), encoding="utf-8")
    os.replace(tmp, cfg_file)
    return load()

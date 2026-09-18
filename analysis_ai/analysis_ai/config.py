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
    # Model per stage. The bake-off (see README) favoured qwen3.6:27b for extraction quality.
    "models": {"extract": "qwen3.6:27b", "chat": "qwen3.6:27b", "embed": "nomic-embed-text"},
    "num_ctx": {"extract": 16384, "chat": 32768},
    # Ollama "think" setting per model; models not listed use their own default.
    "think": {"gpt-oss:20b": "low", "qwen3.6:27b": False},
    # Notes with more text than this (e.g. a whole textbook) are indexed for
    # search only, not summarized by the LLM.
    "max_extract_chars": 150_000,
    "transcript_chunk_seconds": 600,
    "text_chunk_chars": 6000,
    # Retrieval for chat.
    "retrieval_chunk_chars": 1200,
    "retrieval_top_k": 8,
}


def _merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in override.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def load() -> dict:
    cfg_file = DATA_DIR / "config.json"
    if cfg_file.exists():
        return _merge(DEFAULTS, json.loads(cfg_file.read_text(encoding="utf-8")))
    return dict(DEFAULTS)

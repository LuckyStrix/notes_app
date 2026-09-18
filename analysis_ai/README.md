# analysis_ai

An **optional** extension to notes_app: transcribe lecture recordings, extract study cards from them with a local Ollama model, and (planned) roll them up per class and chat/quiz over the result, NotebookLM-style. Fully local; speed is not a goal.

The notes app does not depend on this folder and works identically without it.

## Guarantees

- **Read-only toward notes_app data.** Media is mounted `:ro` (or fetched via `GET` only); nothing here writes to the notes database, `uploads/`, or `postgres-data/`.
- **Own storage.** Everything generated goes under `analysis_ai/data/`, which is gitignored. It is derived from personal course material and this repo is public, so only code and prompts are ever committed.
- **No shared caches.** The Whisper model cache is its own Docker volume (`analysis_ai_whisper_cache`), not the app's.

## Scripts (current state)

`scripts/transcribe.py` — Whisper transcription of one media file to JSON. Always passes an explicit language: Whisper's auto-detect labelled several English lectures as Welsh and produced unusable transcripts. Run it in a throwaway container built from the worker image:

```
docker run --rm --gpus all \
  -v <repo>/uploads:/media:ro \
  -v <repo>/analysis_ai/scripts:/scripts:ro \
  -v <repo>/analysis_ai/data:/out \
  -v analysis_ai_whisper_cache:/root/.cache/huggingface \
  notes_app-worker:latest \
  python /scripts/transcribe.py "/media/<note-id>/<file>" /out/<name>.json --model large-v3 --language en
```

`scripts/bakeoff.py` — runs one transcript through several Ollama models with the same prompt and JSON schema, and saves the study cards plus timing and a crude grounding check side by side:

```
python scripts/bakeoff.py data/<name>.json data/cards lfm2:latest gpt-oss:20b qwen3.6:27b
```

## First bake-off (one 74-minute lecture, single-pass extraction)

| model | time | notes |
|---|---|---|
| `lfm2` | 24 s | Fast, but generic textbook content; missed the exam date/scope entirely and put meta-commentary in "logistics"; duplicate timestamps. |
| `gpt-oss:20b` | 43 s | Specific and granular (13 topics, real numeric example, exam date + review session); one conceptual error (called R/W a capital-to-labour ratio); missed exam scope/format. |
| `qwen3.6:27b` | 201 s | Most accurate and complete (exam date, scope, format, abundance vs. intensity distinction); coarser (5 topics). |

n=1 and judged by reading against the transcript, so treat as a strong hint, not a benchmark. Every card was short (~5 KB for 74 min): single-pass extraction compresses heavily, so chunked map-then-merge extraction is the likely next improvement.

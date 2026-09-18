# analysis_ai

An **optional** extension to notes_app: transcribe lecture recordings, extract study cards with a local Ollama model, roll them up per class, and chat / quiz over the result, NotebookLM-style. Fully local; speed is not a goal (an overnight run is fine).

The notes app does not depend on this folder and works identically without it.

## Guarantees

- **Read-only toward notes_app data.** The only channel to the notes app is `notes_api.py`, which has exactly one verb (`GET`) — a unit test enforces that. Media is mounted `:ro` into the transcription container. Nothing here writes to the notes database, `uploads/`, or `postgres-data/`.
- **Own storage.** Everything generated lives under `analysis_ai/data/` (gitignored). It's derived from personal course material and this repo is public, so only code and prompts are ever committed.
- **Nothing is lost silently.** Notes deleted in the notes app are *flagged* in the mirror, never removed. Files are written atomically. Extraction merges per-chunk results deterministically, so the model can't drop items in a summarising pass.
- **Nothing runs by itself.** Transcription (GPU-heavy) is a manual command; the rest runs only when you invoke it.

## Pipeline

```
notes app (GET only) ──sync──▶ snapshot/ ──┐
uploads/ (read-only) ─transcribe─▶ transcripts/ ─┤
                                             ├─extract─▶ cards/ ──rollup──▶ rollups/ + vault/
                                             └─index────▶ index.db ──┐
                                                                     └─▶ chat / ask  (overview + retrieved passages, cited)
```

| Command | What it does |
|---|---|
| `sync` | Mirror projects, folders and note text from the notes app into `data/snapshot/`. |
| `transcribe [--only ID]` | Whisper `large-v3` with the language **forced** (auto-detect labelled English lectures as Welsh and produced junk). Runs in a throwaway container from the worker image. Skips notes already done. |
| `extract [--project X] [--model M] [--force]` | Per-note study card: each ~6000-char chunk (~9 min of lecture) is extracted on its own (topics, key terms, formulas/rules, examples, **instructor emphasis**, logistics), merged deterministically, then the model writes a title and summary. Cached by hash of (text, prompt version, model). Timestamps are only kept if that marker really exists in the chunk. Documents over `max_extract_chars` (e.g. a textbook) are search-only; notes under 300 chars are kept verbatim. |
| `rollup [--only X]` | Per-folder summaries, a class overview with themes and cross-note connections, and a glossary / exams-and-deadlines / "flagged as important" list assembled straight from the cards with sources. Writes the Obsidian-compatible `data/vault/`. |
| `index` | Chunks raw text (~1200 chars, with timestamp/page), embeds with `nomic-embed-text`, stores in SQLite + FTS5. Search fuses dense and keyword rankings so exact terms still hit. |
| `build` | `sync` + `extract` + `rollup` + `index` (not `transcribe`). |
| `chat [-p CLASS]` / `ask "…"` | Every turn gets the class overview, glossary and exam list plus the top retrieved passages, numbered for `[n]` citations that resolve to note + timestamp/page. In chat: `/quiz [n] [topic]`, `/flashcards`, `/guide`, `/open` (allow labelled outside knowledge), `/strict`, `/new`. |
| `status` | Pipeline progress. |

Typical use:

```
cd analysis_ai
python -m analysis_ai sync
python -m analysis_ai transcribe        # manual, GPU, slow
python -m analysis_ai build             # extract + rollup + index
python -m analysis_ai chat -p "ECON 405"
```

Settings (models per stage, chunk sizes, paths) have defaults in `analysis_ai/config.py` and can be overridden in `data/config.json`. Requirements: Python 3.10+, `numpy`, Ollama, Docker (only for `transcribe`), and the notes app running (only for `sync`).

## Tests

```
cd analysis_ai && python -m unittest discover -s tests -v
```

## Model choice

First bake-off (one 74-minute lecture, single pass; `scripts/bakeoff.py`):

| model | time | notes |
|---|---|---|
| `lfm2` | 24 s | Fast, but generic textbook content; missed the exam date/scope entirely; duplicate timestamps. |
| `gpt-oss:20b` | 43 s | Specific and granular; one conceptual error; missed exam scope/format. |
| `qwen3.6:27b` | 201 s | Most accurate and complete (exam date, scope, format). Default for extract and chat. |

n=1, judged by reading against the transcript — a strong hint, not a benchmark. Single-pass cards were short (~5 KB for 74 min), which is why extraction is now chunked.

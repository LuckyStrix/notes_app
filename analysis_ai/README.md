# analysis_ai

An **optional** add-on to notes_app: transcribe your lecture recordings, turn everything into summary cards with a local Ollama model, roll them up per class, and chat / quiz over the result, NotebookLM-style. Fully local; speed is not a goal.

The notes app does not depend on this folder and works identically without it.

## Using it (web interface)

```
docker compose -f analysis_ai/docker-compose.yml up -d --build     # from the repo root
```

Open **http://localhost:8090** — or `http://<tailscale-ip>:8090` from another device, exactly like the notes app. Once it's running, an **Analysis** link appears in the notes app's header (it disappears again when the add-on is stopped). Stop it with `docker compose -f analysis_ai/docker-compose.yml down`; your data stays in `analysis_ai/data/`.

| Tab | What you do there |
|---|---|
| **Pipeline** | The control room. Every note with status chips (transcribed? summary card up to date? searchable?). Buttons: **Transcribe** (per recording, with a time estimate), **Build card**, **Update class** (builds what's new/edited, then the class overview and search index), **Cancel** on the job list. |
| **Chat** | Pick classes, ask questions. Answers cite `[n]` → note + timestamp/page, with the retrieved passages shown under each answer and a link back into the notes app at that moment. **Study tools**: practice quiz, flashcards, study guide (optionally on a topic). "Only from my notes" or "labelled outside knowledge" mode. |
| **Library** | Per class: overview, themes, how ideas connect, folder summaries, exam/deadline list, "flagged as important by the instructor", searchable glossary, and every note's summary card. |
| **Settings** | Model per stage (from `ollama list`), Whisper model, spoken language, auto-sync, retrieval size. |

**What's automatic and what isn't.** The only thing that happens by itself is a read-only sync every couple of minutes that notices new / edited / deleted notes and marks things out of date. Transcription, summary cards, overviews and indexing only run when you press a button. Jobs run one at a time (they all want the whole GPU); Whisper unloads any Ollama model first so they don't fight over VRAM.

## Guarantees

- **Read-only toward notes_app data.** The only channel to the notes app is `notes_api.py`, which has exactly one verb (`GET`) — a unit test enforces that. `uploads/` is mounted `:ro` and is only read to feed recordings to Whisper. Nothing here writes to the notes database, `uploads/`, or `postgres-data/`.
- **Own storage.** Everything generated lives under `analysis_ai/data/` (gitignored). It's derived from personal course material and this repo is public, so only code and prompts are ever committed.
- **Nothing is lost silently.** Notes deleted in the notes app are *flagged* in the mirror, never removed. A re-transcription keeps the previous transcript in `data/transcripts/previous/`. Files are written atomically. Summary cards are merged deterministically, so the model can't drop items in a summarising pass.
- **Backups of its own data.** Settings can archive `data/` daily or weekly into `../backups` (`AAI_BACKUP_LOCATION`), the same folder the notes app backs up into, keeping the last N. Each archive is read back and checksummed before it counts, and retention only deletes archives made here — the notes app's dumps, and anything else in that folder, are never touched. To use the network share the notes app backs up to, start it with `analysis_ai/docker-compose.nas.yml` as well (command at the top of that file).
- **Its own transcripts.** Whisper's language is forced (default `en`): auto-detect labelled English lectures as Welsh and produced unusable transcripts in the notes app.
- **Locked-down web API.** No login (like the notes app, it belongs on your tailnet), but state-changing requests must be `application/json` (so no other web page can make your browser start jobs), ids are validated before any file access, and Settings can only change a whitelist (models, Whisper, sync, retrieval) — never URLs or paths.

## Pipeline

```
notes app (GET only) ──sync──▶ snapshot/ ──┐
uploads/ (read-only) ─transcribe─▶ transcripts/ ─┤
                                             ├─extract─▶ cards/ ──rollup──▶ rollups/ + vault/
                                             └─index────▶ index.db ──┐
                                                                     └─▶ chat  (overview + retrieved passages, cited)
```

- **transcribe** — Whisper `large-v3`, language forced.
- **extract** — per note, each ~6000-char chunk (~9 min of lecture) is extracted on its own (topics, key terms, formulas/rules, examples, **instructor emphasis**, logistics), merged deterministically, then the model writes a title and summary. Cached by hash of (text, prompt version, model). Model-claimed timestamps are kept only if that marker really exists in the chunk. Documents over `max_extract_chars` (e.g. a textbook) are search-only; notes under 300 characters are kept verbatim.
- **rollup** — per-folder summaries and a class overview with themes and cross-note connections; glossary, exams/deadlines and "flagged as important" assembled straight from the cards with sources. Also writes an Obsidian-compatible markdown vault to `data/vault/`.
- **index** — ~1200-char chunks with timestamp/page, embedded with `nomic-embed-text`, in SQLite + FTS5. Search fuses dense and keyword rankings so exact terms (names, jargon) still hit.
- **chat** — every turn gets the class overview, glossary and exam list plus the top retrieved passages.

## Command line

Everything the web UI does is also available from the CLI (run from `analysis_ai/`):

```
python -m analysis_ai sync | transcribe [--only ID] | extract [--project X] | rollup | index | build
python -m analysis_ai chat -p "ECON 405"      # interactive; /quiz /flashcards /guide /open /strict /new
python -m analysis_ai ask -p "ECON 405" "When is exam 1?"
python -m analysis_ai status
python -m analysis_ai serve                    # the web UI without Docker (transcription then uses docker run)
```

Defaults live in `analysis_ai/config.py`; overrides in `data/config.json` (the Settings tab writes it). Requirements for the CLI: Python 3.10+, `numpy`, `starlette` + `uvicorn` (for `serve`), Ollama, and Docker only for `transcribe`.

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
| `qwen3.6:27b` (Q4_K_M, 17 GB) | 201 s | Most accurate and complete (exam date, scope, format). Was the default, but only 78% fits on a 16 GB GPU, so it ran at ~9.5 tok/s with the CPU pegged. |

Second round, fitting the model into a 16 GB card (`scripts/fitcheck.py`, `scripts/bakeoff.py`; same lecture):

| model | on GPU | speed | notes |
|---|---|---|---|
| `hf.co/unsloth/Qwen3.6-27B-GGUF:Q3_K_M` (13.6 GB) | 94% @8k ctx, 90% @16k | 18.8 tok/s, 121 s | All six verified exam facts, plus a real "not in the textbook, I love to test on it" emphasis the Q4 card missed. Cards were coarser (3 topics, no examples) in single-pass mode. **Best trade-off found; now the default for cards and chat** (8k context for cards, 16k for chat; measured 94% / 90% on the GPU). |
| `hf.co/unsloth/Qwen3.6-27B-GGUF:IQ4_XS` (15.4 GB) | 83% @8k, 81% @16k | not measured | Does not fit; barely better than the Q4 already installed. The bake-off run was stopped by low system memory. |
| `gpt-oss:20b`, thinking `low` | 100% | ~72 tok/s | The setting used in round one. |
| `gpt-oss:20b`, thinking `medium` | 100% | 40 s | Structure collapsed (1 topic) — more thinking made it worse. |
| `gpt-oss:20b`, thinking `high` | 100% | — | Never finishes: with a JSON schema it thinks until the context is full (22,680 tokens) and returns nothing. |

**CPU use with the primary model (`scripts/tune.py`, ctx 8k).** Ollama's automatic split put 64 of 65 layers on the GPU, left ~2 GB of VRAM unused, and the one CPU layer kept all 10 llama-server threads busy-waiting: **40% of the machine's CPU** for the same ~24 tok/s. Requesting `num_gpu=99` puts all 65 layers on the GPU and drops that to **4%** with no change in speed (5% measured while building a real card through the app). Capping `num_thread=4` alone only gets to 16%, but it stays as a safety net: if forcing full offload is ever refused (another app took VRAM), the request is retried without `num_gpu` and the thread cap still applies. Both are set per model in `model_options` in `config.py`.

Partial CPU offload is what makes a model that is slightly too big feel so slow: every token has to wait for the CPU-resident layers, so the GPU idles while the CPU is pegged. A model that is ~90%+ on the GPU behaves much better than one at ~78%.

n=1, judged by reading against the transcript — a strong hint, not a benchmark. Every answer shows the retrieved passages next to it so citations can be checked — local models can attach a `[n]` to a claim the passage doesn't support. (In spot checks against the real notes, the cited claims held up.) Thinking is switched off for Qwen models because thinking plus JSON-schema output can run away until the context is full.

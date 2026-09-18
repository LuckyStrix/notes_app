# notes_app

A self-hosted, AI-powered notes app: multiple projects/classes, text notes, audio/video recordings (with GPU-accelerated transcription), and PDF/Word/text document uploads (with automatic text extraction) — all feeding into an AI keyword graph and a NotebookLM-style chatbot that cites its sources (down to the page, for PDFs), plus literal and semantic search across your notes. Runs entirely in Docker Desktop and is meant to be reached over your own [Tailscale](https://tailscale.com) network — there's no login, since the tailnet boundary *is* the access control.

## Architecture

- **client** — React + TypeScript SPA, served by nginx, which also proxies `/api/*` to the server.
- **server** — FastAPI. CRUD for projects/groups/notes, media upload/streaming, the chat and graph endpoints.
- **worker** — same codebase as `server`, different entrypoint. Runs background jobs (transcription, embedding, keyword extraction) via an RQ queue backed by Redis. This is the only container with a GPU reservation.
- **postgres** — `pgvector/pgvector:pg16`, stores everything including embeddings.
- **redis** — RQ's job queue backing store.

The chat/keyword-extraction LLM is provider-agnostic (Ollama or Claude API, switchable live from **Settings**). Embeddings always run locally via Ollama, regardless of that choice — Anthropic has no embeddings API.

## Prerequisites

- Docker Desktop, with the NVIDIA GPU backend enabled (Settings → Resources → WSL Integration, or Settings → Resources → GPU on newer Docker Desktop). Verify with:
  ```
  docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi
  ```
  If that prints your GPU, you're set.
- [Ollama](https://ollama.com) installed and running natively on the same machine (not in Docker) — the server/worker containers reach it via `host.docker.internal:11434`.
- [Tailscale](https://tailscale.com) installed on this machine and every device you want to use the app from.

## First-time setup

1. **Copy the env file** and adjust if needed (defaults are fine to start):
   ```
   cp .env.example .env
   ```
   Set a real `DB_PASSWORD`. Leave `ANTHROPIC_API_KEY` blank unless you plan to use Claude — you can also set it later from the Settings page instead.

2. **Pull the recommended Ollama models** (sized for a 16GB-class GPU; see the VRAM table in Settings for alternatives):
   ```
   ollama pull nomic-embed-text            # required -- embeddings always use this path
   ollama pull qwen2.5:14b-instruct-q4_K_M # chat/keyword-extraction quality default
   ollama pull llama3.1:8b-instruct-q4_K_M # faster alternative, switchable in Settings
   ```

3. **Build and start everything**:
   ```
   docker compose up -d --build
   ```
   The `server` container runs pending Alembic migrations automatically on boot, so this is the only command you need — no separate migration step.

4. **Open it**: `http://localhost/` on this machine, or from any other device on your tailnet:
   ```
   tailscale ip -4
   ```
   and browse to `http://<that-ip>/`.

## Day-to-day operation

- `docker compose up -d` / `docker compose down` — start/stop the stack.
- `docker compose logs -f worker` — watch transcription/embedding/keyword-extraction jobs as they run.
- Media files live under `./uploads` (host path, configurable via `UPLOAD_LOCATION` in `.env`) and Postgres data under `./postgres-data` (`DB_DATA_LOCATION`) — back up both if you care about the data.
- Downloaded Whisper models are cached in the `whisper-cache` Docker volume, not re-downloaded per job.

## Tests

The server has a small pytest suite covering the pure logic (RAG citation parsing, chunking, graph
significance scoring, storage cleanup) — it doesn't need Postgres/Redis/Ollama running:

```
cd server
pip install -r requirements-dev.txt
pytest
```

## Settings

Everything AI-related is switchable at runtime from the **Settings** page — no restart required:

- **App name**: shown in the nav bar and browser tab title. Purely cosmetic, defaults to "notes_app" if left blank.
- **LLM provider**: Ollama (local, default) or Claude API. Switching to Claude needs an API key (Settings, or `ANTHROPIC_API_KEY` in `.env`).
- **Whisper model size**: `tiny`/`base`/`small`/`medium`/`large-v3`, traded off against transcription speed and VRAM. The worker loads a fresh model per transcription job and releases it immediately after, so a change here takes effect on the very next upload — no idle-unload timer needed, and it never sits resident in VRAM between jobs.
- **Embedding model**: always local. Changing it requires re-indexing every note (different vector space) — the app doesn't do this automatically, so only change it if you're prepared to re-save/re-transcribe notes to rebuild embeddings.

## Chat, citations, and search

- **Chat** answers are grounded strictly in your notes (never outside knowledge), with `[n]` citations linking back to the source note — to a timestamp for audio/video, or a page number for PDFs. Each citation carries a rough confidence hint (high/medium/low) based on how well the cited passage actually matched the question, and chunks that don't clear a minimum relevance bar are excluded from the model's context entirely rather than left in to be guessed at.
- Chat sessions can be **folder-scoped** (answer only from one project subfolder), switched between from the session picker, started fresh with **New chat**, or condensed with **Reset from summary** (an LLM-generated recap seeds a new session so old context isn't just dropped). A banner warns when a session's history is getting long enough that it's worth resetting.
- The **keyword graph**'s per-topic/per-connection summaries have a **Regenerate** button (they're never cached server-side, so this just re-asks the model), and the graph itself updates incrementally as notes change rather than doing a full project rebuild each time — a **Regenerate graph** button is available if you ever want to force a full recompute.
- **Search** (per-project, in the sidebar) offers two modes: **Literal** (exact word/phrase matching via Postgres full-text search) and **Semantic** (matches by meaning via the same embeddings chat uses, so it can find a note discussing a concept even if it never uses your exact words).

## Troubleshooting

- **"Could not reach Ollama"** in Settings: confirm Ollama is running on the host (`ollama list`) and that `OLLAMA_BASE_URL` in `.env` matches how the containers can reach it — `http://host.docker.internal:11434` is the default and should work on Docker Desktop for Windows/Mac without changes.
- **Transcription jobs fail immediately**: check `docker compose logs worker` — most often a missing/renamed Ollama model (for the downstream keyword-extraction step) or a GPU passthrough issue. Re-run the `nvidia-smi` check above.
- **Chat/keyword extraction seems low quality**: local models (especially smaller ones like `llama3.1:8b`) are noticeably behind Claude at following citation instructions and structured extraction. Try `qwen2.5:14b` first; switch to Claude in Settings if you have an API key and want the best quality.
- **Chat answers are missing context that should have matched, or citations feel low-confidence too often**: the relevance thresholds chat retrieval and citation confidence use (`SIMILARITY_FLOOR` and the confidence buckets in `server/app/services/rag.py`) are untuned starting points, not measured values — they're safe to adjust directly in code if they feel too strict or too loose for your notes/embedding model.

## Not built yet (ideas for later)

- Auto-summaries shown in note list views.
- Manual tags alongside the AI keyword graph (`tags`/`note_tags` tables already exist).
- Markdown/PDF export.
- In-browser mic/webcam recording (upload-from-file works today; recording directly in the browser would be nice for capturing notes from a phone on your tailnet).
- Note backlinks/"related notes" surfaced from shared keywords or embedding similarity.

## License

MIT — see [LICENSE](LICENSE).

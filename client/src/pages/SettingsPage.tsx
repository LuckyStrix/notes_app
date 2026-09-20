import { useEffect, useState } from "react";

import { useDatabaseSize, useOllamaModels, useSettings, useUpdateSettings } from "../api/hooks";
import type { AppSettings } from "../api/types";

const RECOMMENDED_CHAT_MODELS = [
  { name: "qwen2.5:14b-instruct-q4_K_M", vram: "~9-10GB", note: "Quality default — best for citations & extraction" },
  { name: "llama3.1:8b-instruct-q4_K_M", vram: "~5-6GB", note: "Fast option" },
];

const WHISPER_MODELS = [
  { name: "tiny", vram: "~1GB", speed: "32x realtime", quality: "Low" },
  { name: "base", vram: "~1GB", speed: "16x realtime", quality: "Low-Medium" },
  { name: "small", vram: "~2GB", speed: "6x realtime", quality: "Medium (default)" },
  { name: "medium", vram: "~5GB", speed: "2x realtime", quality: "High" },
  { name: "large-v3", vram: "~10GB", speed: "1x realtime", quality: "Best" },
];

function bytesToGB(n: number | null): string {
  return n ? `${(n / 1e9).toFixed(1)}GB` : "?";
}

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let value = n / 1024;
  let i = 0;
  while (value >= 1024 && i < units.length - 1) {
    value /= 1024;
    i++;
  }
  return `${value.toFixed(1)} ${units[i]}`;
}

export default function SettingsPage() {
  const { data: settings } = useSettings();
  const { data: ollamaModels, error: ollamaError } = useOllamaModels();
  const { data: databaseSize } = useDatabaseSize();
  const updateSettings = useUpdateSettings();

  const [form, setForm] = useState<Partial<AppSettings> & { anthropic_api_key?: string }>({});
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (settings) setForm(settings);
  }, [settings]);

  if (!settings) return <p className="page">Loading…</p>;

  function set<K extends string>(key: K, value: string | number) {
    setForm((f) => ({ ...f, [key]: value }));
    setSaved(false);
  }

  // Same rule the server enforces: a 2-3 letter lowercase code, or "auto".
  const languageValue = form.whisper_language ?? settings.whisper_language;
  const languageValid = /^(auto|[a-z]{2,3})$/.test(languageValue);

  function save() {
    updateSettings.mutate(form, { onSuccess: () => setSaved(true) });
  }

  return (
    <div className="page">
      <h1>Settings</h1>

      <section className="card">
        <h2>Branding</h2>
        <label className="muted">App name</label>
        <input
          placeholder="notes_app"
          value={form.app_name ?? settings.app_name ?? ""}
          onChange={(e) => set("app_name", e.target.value)}
        />
        <p className="muted">Shown in the nav bar and the browser tab title. Leave blank to use "notes_app".</p>
      </section>

      <section className="card">
        <h2>AI provider</h2>
        <div className="form-inline">
          <label>
            <input
              type="radio"
              name="provider"
              checked={(form.llm_provider ?? settings.llm_provider) === "ollama"}
              onChange={() => set("llm_provider", "ollama")}
            />{" "}
            Ollama (local)
          </label>
          <label>
            <input
              type="radio"
              name="provider"
              checked={(form.llm_provider ?? settings.llm_provider) === "anthropic"}
              onChange={() => set("llm_provider", "anthropic")}
            />{" "}
            Claude API
          </label>
        </div>

        {(form.llm_provider ?? settings.llm_provider) === "ollama" ? (
          <div style={{ marginTop: "1rem" }}>
            <label className="muted">Chat model</label>
            <select
              value={form.ollama_chat_model ?? settings.ollama_chat_model}
              onChange={(e) => set("ollama_chat_model", e.target.value)}
            >
              {!ollamaModels?.some((m) => m.name === (form.ollama_chat_model ?? settings.ollama_chat_model)) && (
                <option value={form.ollama_chat_model ?? settings.ollama_chat_model}>
                  {form.ollama_chat_model ?? settings.ollama_chat_model} (not pulled yet)
                </option>
              )}
              {ollamaModels?.map((m) => (
                <option key={m.name} value={m.name}>
                  {m.name} ({m.parameter_size ?? "?"}, {bytesToGB(m.size_bytes)})
                </option>
              ))}
            </select>
            {ollamaError && (
              <p className="error">Couldn't reach Ollama — is it running and reachable at OLLAMA_BASE_URL?</p>
            )}

            <table className="ref-table">
              <thead><tr><th>Model</th><th>VRAM</th><th>Notes</th></tr></thead>
              <tbody>
                {RECOMMENDED_CHAT_MODELS.map((m) => (
                  <tr key={m.name}>
                    <td><code>{m.name}</code></td>
                    <td>{m.vram}</td>
                    <td>{m.note}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="muted">Not pulled yet? Run <code>ollama pull &lt;model&gt;</code> on the host.</p>

            <label className="muted">Fast model (keyword graph "Generate all")</label>
            <input
              placeholder="e.g. llama3.2:3b-instruct (not pulled yet? ollama pull llama3.2:3b-instruct)"
              value={form.ollama_fast_model ?? settings.ollama_fast_model ?? ""}
              onChange={(e) => set("ollama_fast_model", e.target.value)}
            />
            <p className="muted">
              A small, fast model used only for the keyword graph's "Generate all" button, which sweeps every topic
              and connection in a project to pre-generate a basic summary. Always runs locally via Ollama regardless
              of the chat provider above. Leave blank to disable that button.
            </p>

            <label className="muted">Context window (num_ctx)</label>
            <input
              type="number"
              min={1}
              value={form.num_ctx ?? settings.num_ctx}
              onChange={(e) => set("num_ctx", Number(e.target.value))}
            />
            <p className="muted">
              How much of the RAG context + chat history the model can see at once. Ollama's own default if unset is
              only 2048 tokens, which can silently truncate context on longer conversations. Higher values give
              better-grounded answers at the cost of more VRAM and a slower response — worth raising if you have the
              headroom.
            </p>
          </div>
        ) : (
          <div style={{ marginTop: "1rem" }}>
            <label className="muted">Claude model</label>
            <input
              value={form.anthropic_chat_model ?? settings.anthropic_chat_model}
              onChange={(e) => set("anthropic_chat_model", e.target.value)}
            />
            <label className="muted">API key {settings.has_anthropic_api_key && "(already set — leave blank to keep it)"}</label>
            <input
              type="password"
              placeholder={settings.has_anthropic_api_key ? "••••••••" : "sk-ant-…"}
              onChange={(e) => set("anthropic_api_key", e.target.value)}
            />
          </div>
        )}
      </section>

      <section className="card">
        <h2>Transcription (Whisper)</h2>
        <select value={form.whisper_model ?? settings.whisper_model} onChange={(e) => set("whisper_model", e.target.value)}>
          {WHISPER_MODELS.map((m) => <option key={m.name} value={m.name}>{m.name}</option>)}
        </select>
        <div style={{ margin: "0.75rem 0" }}>
          <label>
            Spoken language{" "}
            <input
              type="text"
              value={languageValue}
              maxLength={4}
              style={{ width: "5rem" }}
              onChange={(e) => set("whisper_language", e.target.value.trim().toLowerCase())}
            />
          </label>
          {!languageValid && <span className="error" style={{ marginLeft: "0.5rem" }}>Use a 2-3 letter code like en, or auto.</span>}
          <p className="muted" style={{ margin: "0.35rem 0 0" }}>
            Recordings are transcribed only when you press Transcribe on a note. The language is set explicitly (default{" "}
            <code>en</code>) because Whisper's auto-detect has labelled English lectures as Welsh and produced unusable
            transcripts. Set <code>auto</code> to let it guess.
          </p>
        </div>
        <table className="ref-table">
          <thead><tr><th>Model</th><th>VRAM</th><th>Speed</th><th>Quality</th></tr></thead>
          <tbody>
            {WHISPER_MODELS.map((m) => (
              <tr key={m.name}>
                <td><code>{m.name}</code></td>
                <td>{m.vram}</td>
                <td>{m.speed}</td>
                <td>{m.quality}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="muted">
          Applies to the next transcription job — the worker loads a fresh model per job, so a change here doesn't
          require a restart.
        </p>
      </section>

      <section className="card">
        <h2>Embeddings</h2>
        <input value={form.embedding_model ?? settings.embedding_model} onChange={(e) => set("embedding_model", e.target.value)} />
        <p className="muted">
          Always runs locally via Ollama regardless of the chat provider above (Claude has no embeddings API).
          Changing this requires re-indexing every note — existing embeddings won't match the new model's vector space.
        </p>
      </section>

      <section className="card">
        <h2>Diagram captioning</h2>
        <input
          placeholder="e.g. qwen2.5vl (not pulled yet? ollama pull qwen2.5vl)"
          value={form.ollama_vision_model ?? settings.ollama_vision_model ?? ""}
          onChange={(e) => set("ollama_vision_model", e.target.value)}
        />
        <p className="muted">
          Used only to auto-caption diagrams you save from a PDF or video (see a note's "Diagrams" tab) — always runs
          locally via Ollama regardless of the chat provider above. Leave blank to skip captioning; saved diagrams
          are still searchable from their OCR'd text alone.
        </p>
      </section>

      <section className="card">
        <h2>Chat retrieval defaults</h2>
        <p className="muted">
          How many note excerpts the AI sees per question, and how relevant one has to be to qualify at all. These
          are the defaults for every project — a project can override either from its own settings page (via the 🔧
          link in its sidebar) if it needs more or less context than usual.
        </p>
        <div className="form-inline">
          <label>
            Context chunk count
            <input
              type="number"
              min={1}
              max={50}
              value={form.default_rag_top_k ?? settings.default_rag_top_k}
              onChange={(e) => set("default_rag_top_k", Number(e.target.value))}
            />
          </label>
          <label>
            Relevance floor
            <input
              type="number"
              min={0}
              max={1}
              step={0.05}
              value={form.default_rag_similarity_floor ?? settings.default_rag_similarity_floor}
              onChange={(e) => set("default_rag_similarity_floor", Number(e.target.value))}
            />
          </label>
        </div>
        <p className="muted">
          Smaller local models tend to get distracted when too many excerpts are crammed into one answer — if chat
          starts saying it "can't find" something that's clearly in your notes, try lowering the chunk count first.
          If answers are missing context that should have matched, try raising the chunk count or lowering the
          relevance floor instead.
        </p>
      </section>

      <section className="card">
        <h2>Backup</h2>
        <p className="muted">
          Download a full snapshot of the database (a <code>pg_dump</code>) as a plain <code>.sql</code> file. Note
          content, chat history, keyword graphs, and settings are all included — uploaded media files (recordings,
          documents, diagrams) live on disk separately and aren't part of this export.
        </p>
        <p className="muted">
          Current database size: {databaseSize ? formatBytes(databaseSize.size_bytes) : "…"} (the actual export file
          is usually somewhat smaller than this).
        </p>
        <a href="/api/settings/database-export" className="button-link" download>Export database</a>
      </section>

      <button onClick={save} disabled={updateSettings.isPending || !languageValid}>Save settings</button>
      {saved && <span className="muted" style={{ marginLeft: "0.75rem" }}>Saved.</span>}
      {updateSettings.isError && (
        <span className="error" style={{ marginLeft: "0.75rem" }}>{(updateSettings.error as Error).message}</span>
      )}
    </div>
  );
}

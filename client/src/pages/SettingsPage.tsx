import { useEffect, useState } from "react";

import { useOllamaModels, useSettings, useUpdateSettings } from "../api/hooks";
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

export default function SettingsPage() {
  const { data: settings } = useSettings();
  const { data: ollamaModels, error: ollamaError } = useOllamaModels();
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

      <button onClick={save} disabled={updateSettings.isPending}>Save settings</button>
      {saved && <span className="muted" style={{ marginLeft: "0.75rem" }}>Saved.</span>}
    </div>
  );
}

import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { useSearch } from "../api/hooks";

const TYPE_ICON: Record<string, string> = { audio: "🎙️", video: "🎬", document: "📄", text: "📝" };

export default function SearchPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const [input, setInput] = useState("");
  const [query, setQuery] = useState("");
  const [mode, setMode] = useState<"literal" | "semantic">("literal");
  const { data: results, isFetching } = useSearch(projectId, query, mode, null);

  if (!projectId) return null;

  return (
    <div className="page search-page">
      <h1>Search</h1>

      <form
        className="form-inline"
        onSubmit={(e) => {
          e.preventDefault();
          setQuery(input.trim());
        }}
      >
        <input
          placeholder="Search this project's notes…"
          value={input}
          onChange={(e) => setInput(e.target.value)}
        />
        <label>
          <input type="radio" name="search-mode" checked={mode === "literal"} onChange={() => setMode("literal")} />{" "}
          Literal
        </label>
        <label>
          <input type="radio" name="search-mode" checked={mode === "semantic"} onChange={() => setMode("semantic")} />{" "}
          Semantic
        </label>
        <button type="submit">Search</button>
      </form>

      <p className="muted" style={{ marginTop: "0.5rem" }}>
        {mode === "literal"
          ? "Matches exact words and phrases."
          : "Matches by meaning — finds notes discussing the concept even without the exact words."}
      </p>

      {isFetching && <p className="muted">Searching…</p>}
      {query && !isFetching && results?.length === 0 && <p className="muted">No matches.</p>}

      <div className="search-results">
        {results?.map((r) => (
          <Link key={r.note_id} to={`/projects/${projectId}/notes/${r.note_id}`} className="card search-result">
            <div className="form-inline" style={{ alignItems: "center" }}>
              <span>{TYPE_ICON[r.type] ?? "📝"}</span>
              <strong>{r.title}</strong>
            </div>
            <p className="muted" style={{ margin: "0.35rem 0 0" }}>{r.snippet}</p>
          </Link>
        ))}
      </div>
    </div>
  );
}

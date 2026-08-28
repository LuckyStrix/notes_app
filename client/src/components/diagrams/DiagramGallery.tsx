import { useState } from "react";

import {
  useDeleteDiagram,
  useDiagramCandidates,
  useDiagrams,
  useGenerateDiagramCandidates,
  useSaveDiagrams,
} from "../../api/hooks";
import type { CandidateStatus } from "../../api/types";

function locationLabel(sourcePage: number | null, sourceTimestamp: number | null): string {
  if (sourcePage !== null) return `p. ${sourcePage}`;
  if (sourceTimestamp !== null) {
    const m = Math.floor(sourceTimestamp / 60);
    const s = Math.floor(sourceTimestamp % 60);
    return `${m}:${s.toString().padStart(2, "0")}`;
  }
  return "";
}

export default function DiagramGallery({ noteId, candidateStatus }: { noteId: string; candidateStatus: CandidateStatus }) {
  const generateCandidates = useGenerateDiagramCandidates(noteId);
  const { data: candidates } = useDiagramCandidates(noteId, { poll: candidateStatus === "processing" });
  const saveDiagrams = useSaveDiagrams(noteId);
  const { data: diagrams } = useDiagrams(noteId);
  const deleteDiagram = useDeleteDiagram(noteId);

  const [selected, setSelected] = useState<Set<string>>(new Set());

  function toggle(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function handleSave() {
    if (selected.size === 0) return;
    saveDiagrams.mutate(Array.from(selected), { onSuccess: () => setSelected(new Set()) });
  }

  return (
    <div className="diagram-gallery">
      <div className="form-inline" style={{ alignItems: "center" }}>
        <button type="button" onClick={() => generateCandidates.mutate()} disabled={candidateStatus === "processing"}>
          {candidateStatus === "processing" ? "Scanning for diagrams…" : "Find diagrams"}
        </button>
        {selected.size > 0 && (
          <button type="button" onClick={handleSave} disabled={saveDiagrams.isPending}>
            Save {selected.size} as {selected.size === 1 ? "diagram" : "diagrams"}
          </button>
        )}
      </div>
      {candidateStatus === "error" && <p className="error">Couldn't scan this file for diagrams — try again.</p>}
      <p className="muted">
        Scans this file for candidate pages/keyframes — pick the ones worth keeping. Saved diagrams get OCR'd and
        captioned, so they're searchable and citable in chat like any other note content.
      </p>

      {candidates && candidates.length > 0 && (
        <div className="diagram-candidate-grid">
          {candidates.map((c) => (
            <button
              key={c.id}
              type="button"
              className={`diagram-thumb${selected.has(c.id) ? " selected" : ""}`}
              onClick={() => toggle(c.id)}
            >
              <img src={`/api/notes/${noteId}/diagrams/candidates/${c.id}/file`} alt="" loading="lazy" />
              <span className="diagram-thumb-label">{locationLabel(c.source_page, c.source_timestamp)}</span>
            </button>
          ))}
        </div>
      )}

      {diagrams && diagrams.length > 0 && (
        <>
          <h3 style={{ marginTop: "1.5rem" }}>Saved diagrams</h3>
          <div className="diagram-candidate-grid">
            {diagrams.map((d) => (
              <div key={d.id} className="diagram-thumb saved">
                <img src={`/api/notes/${noteId}/diagrams/${d.id}/file`} alt={d.caption ?? ""} loading="lazy" />
                <span className="diagram-thumb-label">{locationLabel(d.source_page, d.source_timestamp)}</span>
                {d.status === "processing" && <span className="badge badge-processing">captioning…</span>}
                {d.status === "error" && <span className="badge badge-error">error</span>}
                {d.caption && <p className="muted diagram-caption">{d.caption}</p>}
                <button className="icon-btn" title="Delete" onClick={() => deleteDiagram.mutate(d.id)}>✕</button>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

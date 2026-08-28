import { Link } from "react-router-dom";

import type { Citation } from "../../api/types";

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

export default function CitationLink({ projectId, citation }: { projectId: string; citation: Citation }) {
  const hash =
    citation.start_time !== null
      ? `#t=${citation.start_time}`
      : citation.page_start !== null
        ? `#page=${citation.page_start}`
        : "";
  const confidenceClass = `citation-confidence-${citation.confidence ?? "high"}`;
  const title = citation.confidence === "low" ? `Low confidence match${citation.quote ? ` — ${citation.quote}` : ""}` : citation.quote ?? undefined;
  return (
    <Link
      to={`/projects/${projectId}/notes/${citation.note_id}${hash}`}
      className={`citation-chip ${confidenceClass}`}
      title={title}
    >
      [{citation.ordinal}] {citation.note_title ?? "Note"}
      {citation.start_time !== null && ` @ ${formatTime(citation.start_time)}`}
      {citation.start_time === null && citation.page_start !== null &&
        ` (p. ${citation.page_start === citation.page_end ? citation.page_start : `${citation.page_start}-${citation.page_end}`})`}
      {citation.diagram_id && (
        <img
          className="citation-thumb"
          src={`/api/notes/${citation.note_id}/diagrams/${citation.diagram_id}/file`}
          alt="Cited diagram"
        />
      )}
    </Link>
  );
}

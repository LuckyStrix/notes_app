import type { NoteVersion } from "../../api/types";

function relativeTime(iso: string): string {
  const diffMs = Date.now() - new Date(iso).getTime();
  const minutes = Math.round(diffMs / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  return `${days}d ago`;
}

function firstLine(body: string | null): string {
  if (!body) return "(empty)";
  const line = body.split("\n").find((l) => l.trim().length > 0);
  return line ? line.slice(0, 80) : "(empty)";
}

export default function NoteHistoryPanel({
  versions,
  onRestore,
  onClose,
}: {
  versions: NoteVersion[];
  onRestore: (versionId: string) => void;
  onClose: () => void;
}) {
  return (
    <div className="card note-history-panel">
      <div className="graph-summary-header">
        <h3>Version history</h3>
        <button className="icon-btn" title="Close" onClick={onClose}>✕</button>
      </div>
      {versions.length === 0 && <p className="muted">No earlier versions saved yet — they build up as you edit.</p>}
      {versions.length > 0 && (
        <ul className="note-version-list">
          {versions.map((v) => (
            <li key={v.id} className="note-version-item">
              <div>
                <strong>{v.title}</strong>
                <p className="muted">{firstLine(v.body)}</p>
                <span className="muted">{relativeTime(v.created_at)}</span>
              </div>
              <button className="secondary" onClick={() => onRestore(v.id)}>Restore</button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

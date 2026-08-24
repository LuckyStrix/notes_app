import type { TranscriptSegment } from "../../api/types";

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

interface Props {
  segments: TranscriptSegment[];
  currentTime?: number;
  onSeek: (seconds: number) => void;
}

export default function TranscriptView({ segments, currentTime, onSeek }: Props) {
  return (
    <div className="transcript">
      {segments.map((seg) => {
        const active = currentTime !== undefined && currentTime >= seg.start_time && currentTime < seg.end_time;
        return (
          <button
            key={seg.id}
            className={`transcript-segment${active ? " active" : ""}`}
            onClick={() => onSeek(seg.start_time)}
          >
            <span className="transcript-time">{formatTime(seg.start_time)}</span>
            <span>{seg.text}</span>
          </button>
        );
      })}
    </div>
  );
}

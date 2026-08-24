import { forwardRef, useImperativeHandle, useRef, useState } from "react";

import type { NoteType } from "../../api/types";

export interface MediaPlayerHandle {
  seekTo: (seconds: number) => void;
}

interface Props {
  noteId: string;
  type: Extract<NoteType, "audio" | "video">;
  onTimeUpdate?: (seconds: number) => void;
}

const MediaPlayer = forwardRef<MediaPlayerHandle, Props>(({ noteId, type, onTimeUpdate }, ref) => {
  const mediaRef = useRef<HTMLMediaElement>(null);
  const [error, setError] = useState(false);

  useImperativeHandle(ref, () => ({
    seekTo(seconds: number) {
      const el = mediaRef.current;
      if (!el) return;
      el.currentTime = seconds;
      el.play().catch(() => {
        /* autoplay may be blocked until the user interacts; seeking still worked */
      });
    },
  }));

  const src = `/api/notes/${noteId}/media/file`;

  if (error) {
    return <p className="error">Couldn't load the media file.</p>;
  }

  return type === "video" ? (
    <video
      ref={mediaRef as React.RefObject<HTMLVideoElement>}
      src={src}
      controls
      style={{ width: "100%", borderRadius: 8 }}
      onTimeUpdate={(e) => onTimeUpdate?.(e.currentTarget.currentTime)}
      onError={() => setError(true)}
    />
  ) : (
    <audio
      ref={mediaRef as React.RefObject<HTMLAudioElement>}
      src={src}
      controls
      style={{ width: "100%" }}
      onTimeUpdate={(e) => onTimeUpdate?.(e.currentTarget.currentTime)}
      onError={() => setError(true)}
    />
  );
});

MediaPlayer.displayName = "MediaPlayer";
export default MediaPlayer;

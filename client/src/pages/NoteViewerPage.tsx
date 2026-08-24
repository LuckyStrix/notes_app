import { useEffect, useRef, useState, type ChangeEvent, type KeyboardEvent } from "react";
import { useLocation, useParams } from "react-router-dom";

import { useNote, useNoteFile, useTranscript, useUpdateNote, useUploadMedia } from "../api/hooks";
import MediaPlayer, { type MediaPlayerHandle } from "../components/player/MediaPlayer";
import TranscriptView from "../components/player/TranscriptView";

const DOCUMENT_ACCEPT = ".pdf,.doc,.docx,.txt,.md";
const AUTOSAVE_DELAY_MS = 800;
const INLINE_PREVIEWABLE_EXTENSIONS = new Set(["pdf", "txt", "md"]);

function canPreviewInline(filename: string | null | undefined): boolean {
  if (!filename) return false;
  const ext = filename.toLowerCase().split(".").pop();
  return !!ext && INLINE_PREVIEWABLE_EXTENSIONS.has(ext);
}

export default function NoteViewerPage() {
  const { projectId, noteId } = useParams<{ projectId: string; noteId: string }>();
  const location = useLocation();
  const { data: note } = useNote(noteId);
  const isMedia = note?.type === "audio" || note?.type === "video";
  const isDocument = note?.type === "document";
  const isProcessing = note?.status === "pending" || note?.status === "processing";
  // Text notes are always "ready" from the instant they're created -- nothing
  // in the app ever sets any other status for them, so the badge would just
  // read "ready" forever and tell the user nothing. It's only meaningful for
  // types that go through a background pipeline (upload -> processing -> ready/error).
  const showStatusBadge = note?.type !== "text";

  const { data: noteFile } = useNoteFile(isMedia || isDocument ? noteId : undefined, { poll: isProcessing });
  const { data: transcript } = useTranscript(isMedia && note?.status === "ready" ? noteId : undefined);
  const uploadMedia = useUploadMedia();
  const updateNote = useUpdateNote(projectId!);

  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [currentTime, setCurrentTime] = useState(0);
  // "extracted" = transcript / extracted text (the default); "original" = the
  // uploaded file itself (video player front-and-center, or the raw
  // PDF/text file inline instead of what was pulled out of it).
  const [viewMode, setViewMode] = useState<"extracted" | "original">("extracted");
  const playerRef = useRef<MediaPlayerHandle>(null);
  const documentBodyRef = useRef<HTMLTextAreaElement>(null);
  const titleRef = useRef<HTMLInputElement>(null);
  const titleSaveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const bodySaveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Reset the local draft only when switching to a *different* note, not on
  // every background refetch (e.g. status polling) -- otherwise unsaved
  // in-progress edits would get clobbered.
  useEffect(() => {
    if (note) {
      setTitle(note.title);
      setBody(note.body ?? "");
      setCurrentTime(0);
      setViewMode("extracted");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [note?.id]);

  // For documents, the body only shows up once background extraction
  // finishes (status flips pending/processing -> ready) -- pick that up
  // without clobbering anything the user may have started typing meanwhile.
  useEffect(() => {
    if (note && isDocument && note.status === "ready" && body === "" && note.body) {
      setBody(note.body);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [note?.status, note?.body]);

  useEffect(() => {
    const state = location.state as { focusTitle?: boolean } | null;
    if (state?.focusTitle) {
      titleRef.current?.focus();
      titleRef.current?.select();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [noteId]);

  useEffect(() => {
    if (!noteFile) return;
    const match = location.hash.match(/#t=([\d.]+)/);
    if (!match) return;
    const seconds = parseFloat(match[1]);
    const id = setTimeout(() => playerRef.current?.seekTo(seconds), 300);
    return () => clearTimeout(id);
  }, [noteFile, location.hash]);

  // Approximate scroll-to-page for document citations: the extracted view is
  // a plain editable textarea (not per-page DOM nodes like the transcript's
  // segment list), so we estimate a line number from the marker's character
  // offset and scroll by lineHeight*lineNumber. Wrapped lines throw this off
  // somewhat -- good enough to land in the right neighborhood, not exact.
  useEffect(() => {
    if (!isDocument || note?.status !== "ready" || !note.body) return;
    const match = location.hash.match(/#page=(\d+)/);
    if (!match) return;
    const marker = `--- Page ${match[1]} ---`;
    const offset = note.body.indexOf(marker);
    if (offset === -1) return;
    const lineNumber = note.body.slice(0, offset).split("\n").length - 1;
    const id = setTimeout(() => {
      setViewMode("extracted");
      const el = documentBodyRef.current;
      if (!el) return;
      const lineHeight = parseFloat(getComputedStyle(el).lineHeight) || 24;
      el.scrollTop = lineNumber * lineHeight;
    }, 300);
    return () => clearTimeout(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isDocument, note?.status, note?.body, location.hash]);

  // Flush any pending debounced save immediately when leaving the page
  // (route change, tab close) so a save never just gets silently dropped.
  useEffect(() => {
    return () => {
      if (titleSaveTimer.current) clearTimeout(titleSaveTimer.current);
      if (bodySaveTimer.current) clearTimeout(bodySaveTimer.current);
    };
  }, [noteId]);

  if (!note || !noteId) return null;

  function flushTitleSave(value: string) {
    if (titleSaveTimer.current) {
      clearTimeout(titleSaveTimer.current);
      titleSaveTimer.current = null;
    }
    const trimmed = value.trim() || "Untitled";
    if (trimmed !== note!.title) {
      updateNote.mutate({ noteId: noteId!, payload: { title: trimmed } });
    }
  }

  function handleTitleChange(value: string) {
    setTitle(value);
    if (titleSaveTimer.current) clearTimeout(titleSaveTimer.current);
    titleSaveTimer.current = setTimeout(() => flushTitleSave(value), AUTOSAVE_DELAY_MS);
  }

  function handleTitleBlur() {
    const trimmed = title.trim() || "Untitled";
    setTitle(trimmed);
    flushTitleSave(trimmed);
  }

  function handleTitleKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter") e.currentTarget.blur();
  }

  function flushBodySave(value: string) {
    if (bodySaveTimer.current) {
      clearTimeout(bodySaveTimer.current);
      bodySaveTimer.current = null;
    }
    if (value !== (note!.body ?? "")) {
      updateNote.mutate({ noteId: noteId!, payload: { body: value } });
    }
  }

  function handleBodyChange(value: string) {
    setBody(value);
    if (bodySaveTimer.current) clearTimeout(bodySaveTimer.current);
    bodySaveTimer.current = setTimeout(() => flushBodySave(value), AUTOSAVE_DELAY_MS);
  }

  function handleFileSelected(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (file) uploadMedia.mutate({ noteId: noteId!, file });
  }

  const fileUrl = `/api/notes/${noteId}/media/file`;

  return (
    <div className="note-viewer">
      <input
        ref={titleRef}
        className="note-title-input"
        value={title}
        onChange={(e) => handleTitleChange(e.target.value)}
        onBlur={handleTitleBlur}
        onKeyDown={handleTitleKeyDown}
        placeholder="Untitled"
      />
      {showStatusBadge && (
        <div className="note-meta-row">
          <span className={`badge badge-${note.status}`}>{note.status}</span>
          {note.status === "error" && note.error_message && <span className="error">{note.error_message}</span>}
        </div>
      )}

      <div className="note-body-area">
        {note.type === "text" && (
          <textarea
            className="note-body-textarea"
            value={body}
            placeholder="Start writing…"
            onChange={(e) => handleBodyChange(e.target.value)}
            onBlur={() => flushBodySave(body)}
          />
        )}

        {isDocument && (
          <>
            {!noteFile ? (
              <div>
                <p className="muted">No file uploaded yet.</p>
                <input type="file" accept={DOCUMENT_ACCEPT} onChange={handleFileSelected} disabled={uploadMedia.isPending} />
                {uploadMedia.isPending && <p className="muted">Uploading…</p>}
              </div>
            ) : (
              <div className="note-document-area">
                <div className="view-toggle">
                  <button className={viewMode === "extracted" ? "active" : ""} onClick={() => setViewMode("extracted")}>
                    Extracted text
                  </button>
                  <button className={viewMode === "original" ? "active" : ""} onClick={() => setViewMode("original")}>
                    Original file
                  </button>
                </div>

                {viewMode === "extracted" ? (
                  <>
                    {isProcessing && <p className="muted">Extracting text…</p>}
                    {note.status === "ready" && (
                      <textarea
                        ref={documentBodyRef}
                        className="note-body-textarea"
                        value={body}
                        onChange={(e) => handleBodyChange(e.target.value)}
                        onBlur={() => flushBodySave(body)}
                      />
                    )}
                  </>
                ) : canPreviewInline(noteFile.original_filename) ? (
                  <iframe src={fileUrl} title={noteFile.original_filename ?? "document"} className="document-frame" />
                ) : (
                  <div className="document-frame-fallback">
                    <p className="muted">Preview isn't available for this file type.</p>
                    <a href={fileUrl} target="_blank" rel="noreferrer">
                      Open {noteFile.original_filename}
                    </a>
                  </div>
                )}

                <div style={{ marginTop: "1rem" }}>
                  <label className="muted">Replace file: </label>
                  <input
                    type="file"
                    accept={DOCUMENT_ACCEPT}
                    onChange={handleFileSelected}
                    disabled={uploadMedia.isPending}
                  />
                </div>
              </div>
            )}
          </>
        )}

        {isMedia && (
          <div className="note-media-area">
            {!noteFile ? (
              <div>
                <p className="muted">No file uploaded yet.</p>
                <input
                  type="file"
                  accept={note.type === "video" ? "video/*" : "audio/*"}
                  onChange={handleFileSelected}
                  disabled={uploadMedia.isPending}
                />
                {uploadMedia.isPending && <p className="muted">Uploading…</p>}
              </div>
            ) : (
              <>
                <div className="view-toggle">
                  <button className={viewMode === "extracted" ? "active" : ""} onClick={() => setViewMode("extracted")}>
                    Transcript
                  </button>
                  <button className={viewMode === "original" ? "active" : ""} onClick={() => setViewMode("original")}>
                    Original {note.type}
                  </button>
                </div>

                <MediaPlayer
                  ref={playerRef}
                  noteId={noteId}
                  type={note.type as "audio" | "video"}
                  onTimeUpdate={setCurrentTime}
                />
                <p className="muted" style={{ marginTop: "0.5rem" }}>
                  {noteFile.original_filename}
                  {noteFile.duration_seconds ? ` · ${Math.round(noteFile.duration_seconds)}s` : ""}
                </p>
                {isProcessing && <p className="muted">Transcribing… this page will update automatically.</p>}
                {viewMode === "extracted" && transcript && (
                  <TranscriptView
                    segments={transcript.segments}
                    currentTime={currentTime}
                    onSeek={(t) => playerRef.current?.seekTo(t)}
                  />
                )}
                <div style={{ marginTop: "1rem" }}>
                  <label className="muted">Replace file: </label>
                  <input
                    type="file"
                    accept={note.type === "video" ? "video/*" : "audio/*"}
                    onChange={handleFileSelected}
                    disabled={uploadMedia.isPending}
                  />
                </div>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

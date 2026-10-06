import { useEffect, useRef, useState, type ChangeEvent, type KeyboardEvent } from "react";
import { useLocation, useParams } from "react-router-dom";

import { formatProgress, useUploadState, type UploadState } from "../api/uploads";
import { useNote, useNoteFile, useNoteVersions, useRestoreNoteVersion, useSettings, useTranscribeNote, useTranscript, useUpdateNote, useUploadMedia } from "../api/hooks";
import MediaPlayer, { type MediaPlayerHandle } from "../components/player/MediaPlayer";
import TranscriptView from "../components/player/TranscriptView";
import NoteHistoryPanel from "../components/notes/NoteHistoryPanel";
import DiagramGallery from "../components/diagrams/DiagramGallery";
import MarkdownContent from "../components/MarkdownContent";
import { bodyToAdopt } from "../components/notes/syncBody";

const DOCUMENT_ACCEPT = ".pdf,.doc,.docx,.txt,.md";
const AUTOSAVE_DELAY_MS = 800;
const TEXT_MODE_KEY = "notes.textMode";
type TextMode = "edit" | "preview";

// Text notes open rendered (so **bold**, ## headings, lists and links show as formatting) and
// switch to the plain textarea to edit. An empty note opens for typing; otherwise the last
// choice is remembered per browser. localStorage can throw (private windows), so it's optional.
function preferredTextMode(body: string | null | undefined): TextMode {
  if (!body?.trim()) return "edit";
  try {
    return localStorage.getItem(TEXT_MODE_KEY) === "edit" ? "edit" : "preview";
  } catch {
    return "preview";
  }
}

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
  // Recordings are only transcribed when you press "Transcribe", so an uploaded recording
  // sits at "pending" doing nothing -- that is NOT "processing". (Documents are still
  // extracted automatically, so for them "pending" does mean work is about to happen.)
  const awaitingTranscription = isMedia && note?.status === "pending";
  const isProcessing = note?.status === "processing" || (note?.status === "pending" && !isMedia);
  // Text notes are always "ready" from the instant they're created -- nothing
  // in the app ever sets any other status for them, so the badge would just
  // read "ready" forever and tell the user nothing. It's only meaningful for
  // types that go through a background pipeline (upload -> processing -> ready/error).
  const showStatusBadge = note?.type !== "text";

  const { data: noteFile, isError: noFileOnServer } = useNoteFile(isMedia || isDocument ? noteId : undefined, { poll: isProcessing });
  const upload = useUploadState(noteId);
  const uploading = !!upload?.active;
  const isPdf = (noteFile?.original_filename ?? "").toLowerCase().endsWith(".pdf");
  // Diagram extraction only makes sense for a PDF's pages/images or a
  // video's frames -- docx/txt and audio have no visual content to scan.
  const showDiagramsTab = (isDocument && isPdf) || note?.type === "video";
  const { data: transcript } = useTranscript(isMedia && note?.status === "ready" ? noteId : undefined);
  const uploadMedia = useUploadMedia();
  const transcribeNote = useTranscribeNote(projectId);
  const { data: appSettings } = useSettings();
  const updateNote = useUpdateNote(projectId!);
  const restoreVersion = useRestoreNoteVersion(projectId!);
  const { data: versions } = useNoteVersions(noteId);
  const [historyOpen, setHistoryOpen] = useState(false);

  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [currentTime, setCurrentTime] = useState(0);
  // "extracted" = transcript / extracted text (the default); "original" = the
  // uploaded file itself (video player front-and-center, or the raw
  // PDF/text file inline instead of what was pulled out of it).
  const [viewMode, setViewMode] = useState<"extracted" | "original" | "diagrams">("extracted");
  const [textMode, setTextMode] = useState<TextMode>("edit");
  const playerRef = useRef<MediaPlayerHandle>(null);
  const documentBodyRef = useRef<HTMLTextAreaElement>(null);
  const titleRef = useRef<HTMLInputElement>(null);
  const titleSaveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const bodySaveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Mirrors of the latest title/body, kept current every render so the
  // unmount-cleanup effect below (deliberately scoped to [noteId] only, so it
  // doesn't re-fire on every keystroke) can still flush the *latest* values
  // instead of whatever was in scope when it was set up.
  const latestTitle = useRef(title);
  latestTitle.current = title;
  const latestBody = useRef(body);
  latestBody.current = body;
  // The server body this editor last saw (adopted, or written by its own save); see syncBody.ts.
  const serverBody = useRef("");

  // Reset the local draft only when switching to a *different* note, not on
  // every background refetch (e.g. status polling) -- otherwise unsaved
  // in-progress edits would get clobbered.
  useEffect(() => {
    if (note) {
      setTitle(note.title);
      setBody(note.body ?? "");
      serverBody.current = note.body ?? "";
      setCurrentTime(0);
      setViewMode("extracted");
      setTextMode(preferredTextMode(note.body));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [note?.id]);

  // Pick up body changes made elsewhere while this note is open, unless there are unsaved
  // local edits (those win and are saved as usual). The note-id effect above handles the
  // initial load, so this only reacts once serverBody has been seeded.
  useEffect(() => {
    if (!note || note.type !== "text" || note.id !== noteId) return;
    const newServer = note.body ?? "";
    const adopt = bodyToAdopt({
      serverBody: serverBody.current,
      draft: latestBody.current,
      newServer,
      savePending: bodySaveTimer.current !== null,
    });
    serverBody.current = newServer;
    if (adopt !== null) setBody(adopt);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [note?.body]);

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
  // (route change) so a save never just gets silently dropped. Reads from
  // the latestTitle/latestBody refs above, not the title/body closed over
  // when this effect was set up -- otherwise a route change more than one
  // render after the last keystroke would flush stale values.
  useEffect(() => {
    return () => {
      if (titleSaveTimer.current) {
        clearTimeout(titleSaveTimer.current);
        flushTitleSave(latestTitle.current, true);
      }
      if (bodySaveTimer.current) {
        clearTimeout(bodySaveTimer.current);
        flushBodySave(latestBody.current, true);
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [noteId]);

  // Tab-close/backgrounding safety net: a normal fetch-based mutation can be
  // cancelled mid-flight on unload, so this uses navigator.sendBeacon (fire-
  // and-forget, survives the page going away) against a dedicated endpoint
  // instead of the regular useUpdateNote mutation path.
  useEffect(() => {
    function flushViaBeacon() {
      if (!note || !noteId) return;
      const payload: Record<string, unknown> = { force_version: true };
      let hasChanges = false;
      const trimmedTitle = title.trim() || "Untitled";
      if (trimmedTitle !== note.title) {
        payload.title = trimmedTitle;
        hasChanges = true;
      }
      if (body !== (note.body ?? "")) {
        payload.body = body;
        hasChanges = true;
      }
      if (!hasChanges) return;
      const blob = new Blob([JSON.stringify(payload)], { type: "application/json" });
      navigator.sendBeacon(`/api/notes/${noteId}/autosave-beacon`, blob);
    }

    function handleVisibilityChange() {
      if (document.visibilityState === "hidden") flushViaBeacon();
    }

    window.addEventListener("beforeunload", flushViaBeacon);
    document.addEventListener("visibilitychange", handleVisibilityChange);
    return () => {
      window.removeEventListener("beforeunload", flushViaBeacon);
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, [note, noteId, title, body]);

  if (!note || !noteId) return null;

  function flushTitleSave(value: string, force = false) {
    if (titleSaveTimer.current) {
      clearTimeout(titleSaveTimer.current);
      titleSaveTimer.current = null;
    }
    const trimmed = value.trim() || "Untitled";
    if (trimmed !== note!.title) {
      updateNote.mutate({ noteId: noteId!, payload: { title: trimmed, force_version: force } });
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
    flushTitleSave(trimmed, true);
  }

  function handleTitleKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter") e.currentTarget.blur();
  }

  function flushBodySave(value: string, force = false) {
    if (bodySaveTimer.current) {
      clearTimeout(bodySaveTimer.current);
      bodySaveTimer.current = null;
    }
    if (value !== (note!.body ?? "")) {
      updateNote.mutate({ noteId: noteId!, payload: { body: value, force_version: force } });
    }
  }

  // Clicking a toggle button blurs the textarea first, so any pending edit is flushed (and
  // versioned) before the rendered view appears.
  function chooseTextMode(mode: TextMode) {
    setTextMode(mode);
    try {
      localStorage.setItem(TEXT_MODE_KEY, mode);
    } catch {
      /* per-browser convenience only */
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
      <div className="note-title-row">
        <input
          ref={titleRef}
          className="note-title-input"
          value={title}
          onChange={(e) => handleTitleChange(e.target.value)}
          onBlur={handleTitleBlur}
          onKeyDown={handleTitleKeyDown}
          placeholder="Untitled"
        />
        <button
          type="button"
          className="icon-btn"
          title="Version history"
          onClick={() => setHistoryOpen((v) => !v)}
        >
          🕘 History
        </button>
      </div>

      {historyOpen && (
        <NoteHistoryPanel
          versions={versions ?? []}
          onRestore={(versionId) => {
            if (confirm("Restore this version? Your current title/body will be saved as a new version first.")) {
              restoreVersion.mutate({ noteId: noteId!, versionId });
            }
          }}
          onClose={() => setHistoryOpen(false)}
        />
      )}

      {showStatusBadge && (
        <div className="note-meta-row">
          <span className={`badge badge-${note.status}`}>{uploading ? "uploading" : awaitingTranscription ? (noFileOnServer ? "no file" : "not transcribed") : note.status}</span>
          {note.status === "error" && note.error_message && <span className="error">{note.error_message}</span>}
        </div>
      )}

      <div className="note-body-area">
        {note.type === "text" && (
          <>
            <div className="view-toggle">
              <button className={textMode === "preview" ? "active" : ""} onClick={() => chooseTextMode("preview")}>
                Preview
              </button>
              <button className={textMode === "edit" ? "active" : ""} onClick={() => chooseTextMode("edit")}>
                Edit
              </button>
            </div>
            {textMode === "edit" ? (
              <textarea
                className="note-body-textarea"
                value={body}
                placeholder="Start writing…"
                onChange={(e) => handleBodyChange(e.target.value)}
                onBlur={() => flushBodySave(body, true)}
              />
            ) : (
              <div className="note-body-preview" title="Double-click to edit" onDoubleClick={() => chooseTextMode("edit")}>
                {body.trim() ? <MarkdownContent content={body} /> : <p className="muted">Nothing to show yet. Click Edit to start writing.</p>}
              </div>
            )}
          </>
        )}

        {isDocument && (
          <>
            {!noteFile ? (
              <div>
                <p className="muted">
                  No file uploaded yet.{noFileOnServer && !upload && " If you uploaded one before, it didn't finish — choose it again."}
                </p>
                <input type="file" accept={DOCUMENT_ACCEPT} onChange={handleFileSelected} disabled={uploading} />
                <UploadStatus upload={upload} />
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
                  {showDiagramsTab && (
                    <button className={viewMode === "diagrams" ? "active" : ""} onClick={() => setViewMode("diagrams")}>
                      Diagrams
                    </button>
                  )}
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
                        onBlur={() => flushBodySave(body, true)}
                      />
                    )}
                  </>
                ) : viewMode === "diagrams" ? (
                  <DiagramGallery noteId={noteId} candidateStatus={noteFile.candidate_status} />
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
                    disabled={uploading}
                  />
                  <UploadStatus upload={upload} />
                </div>
              </div>
            )}
          </>
        )}

        {isMedia && (
          <div className="note-media-area">
            {!noteFile ? (
              <div>
                <p className="muted">
                  No file uploaded yet.{noFileOnServer && !upload && " If you uploaded one before, it didn't finish — choose it again."}
                </p>
                <input
                  type="file"
                  accept={note.type === "video" ? "video/*" : "audio/*"}
                  onChange={handleFileSelected}
                  disabled={uploading}
                />
                <UploadStatus upload={upload} />
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
                  {showDiagramsTab && (
                    <button className={viewMode === "diagrams" ? "active" : ""} onClick={() => setViewMode("diagrams")}>
                      Diagrams
                    </button>
                  )}
                </div>

                {viewMode === "diagrams" ? (
                  <DiagramGallery noteId={noteId} candidateStatus={noteFile.candidate_status} />
                ) : (
                  <>
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
                    {(awaitingTranscription || note.status === "error") && (
                      <div className="card" style={{ marginTop: "0.75rem" }}>
                        <p style={{ marginTop: 0 }}>
                          {note.status === "error"
                            ? "Transcription didn't finish. You can try again."
                            : "This recording hasn't been transcribed yet."}
                        </p>
                        <p className="muted">
                          Transcription uses your GPU and can take a while, so it only starts when you ask.
                          {appSettings && (
                            <> It will use the <code>{appSettings.whisper_model}</code> model with language{" "}
                            <code>{appSettings.whisper_language}</code> (change under Settings).</>
                          )}
                        </p>
                        <button onClick={() => transcribeNote.mutate(noteId!)} disabled={transcribeNote.isPending}>
                          {transcribeNote.isPending ? "Starting…" : note.status === "error" ? "Try again" : "Transcribe"}
                        </button>
                        {transcribeNote.isError && (
                          <p className="error">{(transcribeNote.error as Error).message}</p>
                        )}
                      </div>
                    )}
                    {note.status === "processing" && <p className="muted">Transcribing… this page will update automatically.</p>}
                    {viewMode === "extracted" && transcript && (
                      <TranscriptView
                        segments={transcript.segments}
                        currentTime={currentTime}
                        onSeek={(t) => playerRef.current?.seekTo(t)}
                      />
                    )}
                  </>
                )}
                <div style={{ marginTop: "1rem" }}>
                  <label className="muted">Replace file: </label>
                  <input
                    type="file"
                    accept={note.type === "video" ? "video/*" : "audio/*"}
                    onChange={handleFileSelected}
                    disabled={uploading}
                  />
                  <UploadStatus upload={upload} />
                </div>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function UploadStatus({ upload }: { upload: UploadState | undefined }) {
  if (!upload) return null;
  if (upload.error) return <p className="error">{upload.error} Choose the file again to retry.</p>;
  if (!upload.active) return null;
  const sent = upload.total > 0 && upload.loaded >= upload.total;
  return (
    <div className="upload-status">
      <progress value={upload.loaded} max={upload.total || 1} />
      <span className="muted">
        {sent ? "Saving on the server…" : `Uploading ${upload.fileName} · ${formatProgress(upload)}`} — keep this tab open.
      </span>
    </div>
  );
}

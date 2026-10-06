import { useSyncExternalStore } from "react";

import type { NoteFile } from "./types";

// Uploads are tracked here, outside any component, because they outlive the page that
// started them: the sidebar creates a note, navigates to it, and only then sends the file.
// Any view can show the progress (or the failure) for a note by its id.
//
// fetch() can't report upload progress, so this uses XMLHttpRequest.

export interface UploadState {
  fileName: string;
  loaded: number;
  total: number;
  active: boolean;
  error: string | null;
}

let uploads: Record<string, UploadState> = {};
const listeners = new Set<() => void>();

function set(noteId: string, patch: Partial<UploadState>) {
  uploads = { ...uploads, [noteId]: { ...uploads[noteId], ...patch } };
  listeners.forEach((l) => l());
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

// Closing or reloading the tab mid-upload throws the file away and leaves an empty note,
// so ask the browser to confirm first.
window.addEventListener("beforeunload", (e) => {
  if (Object.values(uploads).some((u) => u.active)) e.preventDefault();
});

export function uploadNoteFile(noteId: string, file: File): Promise<NoteFile> {
  set(noteId, { fileName: file.name, loaded: 0, total: file.size, active: true, error: null });
  return new Promise((resolve, reject) => {
    const fail = (message: string) => {
      set(noteId, { active: false, error: message });
      reject(new Error(message));
    };
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `/api/notes/${noteId}/media`);
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) set(noteId, { loaded: e.loaded, total: e.total });
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        set(noteId, { active: false, loaded: file.size });
        resolve(JSON.parse(xhr.responseText) as NoteFile);
        return;
      }
      let detail = xhr.statusText;
      try {
        detail = JSON.parse(xhr.responseText).detail ?? detail;
      } catch {
        // not JSON (e.g. an nginx error page) -- keep the status text
      }
      fail(`Upload failed (${xhr.status}${detail ? `: ${detail}` : ""}).`);
    };
    xhr.onerror = () => fail("Upload failed: the connection to the server was lost.");
    xhr.onabort = () => fail("Upload was cancelled.");
    const form = new FormData();
    form.append("file", file);
    xhr.send(form);
  });
}

export function useUploadState(noteId: string | undefined): UploadState | undefined {
  return useSyncExternalStore(subscribe, () => (noteId ? uploads[noteId] : undefined));
}

export function formatProgress(u: UploadState): string {
  const mb = (n: number) => (n / 1024 / 1024).toFixed(n < 10 * 1024 * 1024 ? 1 : 0);
  const pct = u.total ? Math.floor((u.loaded / u.total) * 100) : 0;
  return `${pct}% · ${mb(u.loaded)} / ${mb(u.total)} MB`;
}

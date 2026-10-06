// What an open text note's editor should do when the server's copy of the body changes
// underneath it (e.g. the daily_brief job rewriting Brief Control, or another device saving).
//
// Without this the editor kept showing its old draft, and its tab-hide/close safety net
// then saved that stale draft over the server's newer text.
//
//   serverBody  the server body we last saw (adopted or written by our own save)
//   draft       what the editor currently holds
//   newServer   the body the server has now
//   savePending an autosave is queued but has not fired yet
//
// Returns the text the editor should show, or null to leave the draft alone. Unsaved local
// edits always win over an external change: they are saved on the next flush as before.
export function bodyToAdopt(args: {
  serverBody: string;
  draft: string;
  newServer: string;
  savePending: boolean;
}): string | null {
  const { serverBody, draft, newServer, savePending } = args;
  if (newServer === serverBody || newServer === draft) return null;
  const hasUnsavedEdits = savePending || draft !== serverBody;
  return hasUnsavedEdits ? null : newServer;
}

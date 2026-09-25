import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import type { AppSettings, BackupList, ChatMessage, ChatSession, Diagram, DiagramCandidate, Graph, GraphSummary, Group, Note, NoteFile, NoteType, NoteVersion, Project, SearchResult, Transcript } from "./types";

// Projects

export function useProjects() {
  return useQuery({ queryKey: ["projects"], queryFn: () => api.get<Project[]>("/projects") });
}

export function useProject(projectId: string | undefined) {
  return useQuery({
    queryKey: ["projects", projectId],
    queryFn: () => api.get<Project>(`/projects/${projectId}`),
    enabled: !!projectId,
    // Self-polls while a graph rebuild or a "Generate All" summary batch is
    // in flight (mirrors Note.status polling elsewhere) so callers don't
    // need to know in advance whether one is running.
    refetchInterval: (query) =>
      query.state.data?.graph_status === "processing" || query.state.data?.summary_generation_status === "processing"
        ? 2000
        : false,
  });
}

export function useCreateProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: { name: string; description?: string }) => api.post<Project>("/projects", payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["projects"] }),
  });
}

export function useUpdateProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      projectId,
      payload,
    }: {
      projectId: string;
      payload: {
        name?: string;
        description?: string | null;
        rag_top_k?: number | null;
        rag_similarity_floor?: number | null;
      };
    }) => api.patch<Project>(`/projects/${projectId}`, payload),
    onSuccess: (_data, { projectId }) => {
      qc.invalidateQueries({ queryKey: ["projects"] });
      qc.invalidateQueries({ queryKey: ["projects", projectId] });
    },
  });
}

export function useReorderProjects() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (projectIds: string[]) => api.patch<Project[]>("/projects/reorder", { project_ids: projectIds }),
    onMutate: async (projectIds) => {
      await qc.cancelQueries({ queryKey: ["projects"] });
      const previous = qc.getQueryData<Project[]>(["projects"]);
      if (previous) {
        const byId = new Map(previous.map((p) => [p.id, p]));
        const reordered = projectIds.map((id) => byId.get(id)).filter((p): p is Project => !!p);
        qc.setQueryData(["projects"], reordered);
      }
      return { previous };
    },
    onError: (_err, _projectIds, context) => {
      if (context?.previous) qc.setQueryData(["projects"], context.previous);
    },
    onSettled: () => qc.invalidateQueries({ queryKey: ["projects"] }),
  });
}

export function useDeleteProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (projectId: string) => api.delete(`/projects/${projectId}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["projects"] }),
  });
}

// Groups

export function useGroups(projectId: string | undefined) {
  return useQuery({
    queryKey: ["projects", projectId, "groups"],
    queryFn: () => api.get<Group[]>(`/projects/${projectId}/groups`),
    enabled: !!projectId,
  });
}

export function useCreateGroup(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: { name: string; parent_group_id?: string | null }) =>
      api.post<Group>(`/projects/${projectId}/groups`, payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["projects", projectId, "groups"] }),
  });
}

export function useDeleteGroup(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (groupId: string) => api.delete(`/groups/${groupId}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["projects", projectId, "groups"] });
      // Notes in the deleted group(s) fall back to ungrouped (FK is ON DELETE SET NULL), not deleted.
      qc.invalidateQueries({ queryKey: ["notes", { projectId }] });
    },
  });
}

export function useUpdateGroup(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ groupId, payload }: { groupId: string; payload: { name?: string; parent_group_id?: string | null } }) =>
      api.patch<Group>(`/groups/${groupId}`, payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["projects", projectId, "groups"] }),
  });
}

// Notes

export function useNotes(projectId: string | undefined) {
  return useQuery({
    queryKey: ["notes", { projectId }],
    queryFn: () => api.get<Note[]>(`/notes?project_id=${projectId}`),
    enabled: !!projectId,
    // Self-polls while any note is being transcribed/extracted so the sidebar dot clears on its own.
    refetchInterval: (query) => (query.state.data?.some((n) => n.status === "processing") ? 3000 : false),
  });
}

export function useNote(noteId: string | undefined) {
  return useQuery({
    queryKey: ["notes", noteId],
    queryFn: () => api.get<Note>(`/notes/${noteId}`),
    enabled: !!noteId,
    // Same idea: pick up processing -> ready/error without needing a refresh.
    refetchInterval: (query) => (query.state.data?.status === "processing" ? 3000 : false),
  });
}

export function useCreateNote(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: { title: string; body?: string; type: NoteType; group_id?: string | null }) =>
      api.post<Note>("/notes", { ...payload, project_id: projectId }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["notes", { projectId }] }),
  });
}

export function useUpdateNote(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      noteId,
      payload,
    }: {
      noteId: string;
      payload: { title?: string; body?: string; group_id?: string | null; force_version?: boolean };
    }) => api.patch<Note>(`/notes/${noteId}`, payload),
    onSuccess: (_data, { noteId }) => {
      qc.invalidateQueries({ queryKey: ["notes", { projectId }] });
      qc.invalidateQueries({ queryKey: ["notes", noteId] });
      qc.invalidateQueries({ queryKey: ["notes", noteId, "versions"] });
    },
  });
}

export function useNoteVersions(noteId: string | undefined) {
  return useQuery({
    queryKey: ["notes", noteId, "versions"],
    queryFn: () => api.get<NoteVersion[]>(`/notes/${noteId}/versions`),
    enabled: !!noteId,
  });
}

export function useRestoreNoteVersion(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ noteId, versionId }: { noteId: string; versionId: string }) =>
      api.post<Note>(`/notes/${noteId}/versions/${versionId}/restore`, {}),
    onSuccess: (_data, { noteId }) => {
      qc.invalidateQueries({ queryKey: ["notes", { projectId }] });
      qc.invalidateQueries({ queryKey: ["notes", noteId] });
      qc.invalidateQueries({ queryKey: ["notes", noteId, "versions"] });
    },
  });
}

export function useDeleteNote(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (noteId: string) => api.delete(`/notes/${noteId}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["notes", { projectId }] }),
  });
}

// Media / transcripts

export function useNoteFile(noteId: string | undefined, opts?: { poll?: boolean }) {
  return useQuery({
    queryKey: ["notes", noteId, "file"],
    queryFn: () => api.get<NoteFile>(`/notes/${noteId}/media`),
    enabled: !!noteId,
    retry: false,
    refetchInterval: opts?.poll ? 3000 : false,
  });
}

export function useTranscript(noteId: string | undefined, opts?: { poll?: boolean }) {
  return useQuery({
    queryKey: ["notes", noteId, "transcript"],
    queryFn: () => api.get<Transcript>(`/notes/${noteId}/transcript`),
    enabled: !!noteId,
    retry: false,
    refetchInterval: opts?.poll ? 3000 : false,
  });
}

// Transcription is manual: uploading a recording does not start it.
export function useTranscribeNote(projectId: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (noteId: string) => api.post<Note>(`/notes/${noteId}/transcribe`, {}),
    onSuccess: (_data, noteId) => {
      qc.invalidateQueries({ queryKey: ["notes", noteId] });
      qc.invalidateQueries({ queryKey: ["notes", { projectId }] });
    },
  });
}

export function useUploadMedia() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ noteId, file }: { noteId: string; file: File }) =>
      api.upload<NoteFile>(`/notes/${noteId}/media`, file),
    onSuccess: (_data, { noteId }) => {
      qc.invalidateQueries({ queryKey: ["notes", noteId] });
      qc.invalidateQueries({ queryKey: ["notes", noteId, "file"] });
    },
  });
}

// Diagrams

export function useGenerateDiagramCandidates(noteId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post(`/notes/${noteId}/diagrams/generate-candidates`, {}),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["notes", noteId, "file"] });
      qc.invalidateQueries({ queryKey: ["notes", noteId, "diagram-candidates"] });
    },
  });
}

export function useDiagramCandidates(noteId: string | undefined, opts?: { poll?: boolean }) {
  return useQuery({
    queryKey: ["notes", noteId, "diagram-candidates"],
    queryFn: () => api.get<DiagramCandidate[]>(`/notes/${noteId}/diagrams/candidates`),
    enabled: !!noteId,
    refetchInterval: opts?.poll ? 3000 : false,
  });
}

export function useSaveDiagrams(noteId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (candidateIds: string[]) =>
      api.post<Diagram[]>(`/notes/${noteId}/diagrams`, { candidate_ids: candidateIds }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["notes", noteId, "diagrams"] }),
  });
}

export function useDiagrams(noteId: string | undefined) {
  return useQuery({
    queryKey: ["notes", noteId, "diagrams"],
    queryFn: () => api.get<Diagram[]>(`/notes/${noteId}/diagrams`),
    enabled: !!noteId,
    // Self-polls while any diagram is still being OCR'd/captioned.
    refetchInterval: (query) => (query.state.data?.some((d) => d.status === "processing") ? 3000 : false),
  });
}

export function useDeleteDiagram(noteId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (diagramId: string) => api.delete(`/notes/${noteId}/diagrams/${diagramId}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["notes", noteId, "diagrams"] }),
  });
}

// Graph

export function useGraph(projectId: string | undefined, significance: number) {
  return useQuery({
    queryKey: ["graph", projectId, significance],
    queryFn: () => api.get<Graph>(`/projects/${projectId}/graph?significance=${significance}`),
    enabled: !!projectId,
    placeholderData: (prev) => prev,
  });
}

export function useKeywordSummary(projectId: string | undefined, keywordId: string | undefined) {
  return useQuery({
    queryKey: ["graph-summary", "keyword", projectId, keywordId],
    queryFn: () => api.get<GraphSummary>(`/projects/${projectId}/graph/keywords/${keywordId}/summary`),
    enabled: !!projectId && !!keywordId,
    retry: false, // a fresh graph rebuild can make a previously-selected id 404 briefly
  });
}

export function useEdgeSummary(projectId: string | undefined, source: string | undefined, target: string | undefined) {
  return useQuery({
    queryKey: ["graph-summary", "edge", projectId, source, target],
    queryFn: () => api.get<GraphSummary>(`/projects/${projectId}/graph/edges/summary?source=${source}&target=${target}`),
    enabled: !!projectId && !!source && !!target,
    retry: false,
  });
}

export function useGenerateKeywordQualitySummary(projectId: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (keywordId: string) =>
      api.post<GraphSummary>(`/projects/${projectId}/graph/keywords/${keywordId}/summary/quality`, {}),
    onSuccess: (data, keywordId) =>
      qc.setQueryData(["graph-summary", "keyword", projectId, keywordId], data),
  });
}

export function useGenerateEdgeQualitySummary(projectId: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ source, target }: { source: string; target: string }) =>
      api.post<GraphSummary>(`/projects/${projectId}/graph/edges/summary/quality?source=${source}&target=${target}`, {}),
    onSuccess: (data, { source, target }) =>
      qc.setQueryData(["graph-summary", "edge", projectId, source, target], data),
  });
}

export function useGenerateAllSummaries(projectId: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<{ status: string; total: number }>(`/projects/${projectId}/graph/summaries/generate-all`, {}),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["projects", projectId] }),
  });
}

export function useRebuildGraph(projectId: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post(`/projects/${projectId}/graph/rebuild`, {}),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["projects", projectId] }),
  });
}

// Chat

export function useChatSessions(projectId: string | undefined) {
  return useQuery({
    queryKey: ["chat", "sessions", { projectId }],
    queryFn: () => api.get<ChatSession[]>(`/chat/sessions?project_id=${projectId}`),
    enabled: !!projectId,
  });
}

export function useCreateChatSession(projectId: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<ChatSession>("/chat/sessions", { project_id: projectId }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["chat", "sessions", { projectId }] }),
  });
}

export function useChatMessages(sessionId: string | undefined) {
  return useQuery({
    queryKey: ["chat", "sessions", sessionId, "messages"],
    queryFn: () => api.get<ChatMessage[]>(`/chat/sessions/${sessionId}/messages`),
    enabled: !!sessionId,
  });
}

export function useSummarizeResetSession(projectId: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (sessionId: string) => api.post<ChatSession>(`/chat/sessions/${sessionId}/summarize-reset`, {}),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["chat", "sessions", { projectId }] }),
  });
}

// Search

export function useSearch(
  projectId: string | undefined,
  q: string,
  mode: "literal" | "semantic",
  groupId: string | null,
) {
  return useQuery({
    queryKey: ["search", projectId, q, mode, groupId],
    queryFn: () =>
      api.get<SearchResult[]>(
        `/projects/${projectId}/search?q=${encodeURIComponent(q)}&mode=${mode}${groupId ? `&group_id=${groupId}` : ""}`,
      ),
    enabled: !!projectId && !!q,
  });
}

// Settings

export function useSettings() {
  return useQuery({ queryKey: ["settings"], queryFn: () => api.get<AppSettings>("/settings") });
}

export function useUpdateSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: Partial<AppSettings> & { anthropic_api_key?: string }) =>
      api.put<AppSettings>("/settings", payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["settings"] }),
  });
}

export interface OllamaModel {
  name: string;
  parameter_size: string | null;
  quantization: string | null;
  size_bytes: number | null;
}

export function useOllamaModels() {
  return useQuery({
    queryKey: ["settings", "ollama-models"],
    queryFn: () => api.get<OllamaModel[]>("/settings/ollama-models"),
    retry: false,
  });
}

export function useDatabaseSize() {
  return useQuery({
    queryKey: ["settings", "database-size"],
    queryFn: () => api.get<{ size_bytes: number }>("/settings/database-size"),
  });
}

// Backups

export function useBackups() {
  return useQuery({
    queryKey: ["settings", "backups"],
    queryFn: () => api.get<BackupList>("/settings/backups"),
    // Backups run in the worker, so the only way to notice one finishing is to ask again.
    refetchInterval: 5000,
  });
}

export function useRunBackup() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (kind: "db" | "media") =>
      api.post<{ job_id: string }>(kind === "media" ? "/settings/backups/media" : "/settings/backups/run", {}),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["settings", "backups"] }),
  });
}

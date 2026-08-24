import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import type { AppSettings, ChatMessage, ChatSession, Graph, GraphSummary, Group, Note, NoteFile, NoteType, Project, SearchResult, Transcript } from "./types";

// Projects

export function useProjects() {
  return useQuery({ queryKey: ["projects"], queryFn: () => api.get<Project[]>("/projects") });
}

export function useProject(projectId: string | undefined) {
  return useQuery({
    queryKey: ["projects", projectId],
    queryFn: () => api.get<Project>(`/projects/${projectId}`),
    enabled: !!projectId,
  });
}

export function useCreateProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: { name: string; description?: string }) => api.post<Project>("/projects", payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["projects"] }),
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
  });
}

export function useNote(noteId: string | undefined) {
  return useQuery({
    queryKey: ["notes", noteId],
    queryFn: () => api.get<Note>(`/notes/${noteId}`),
    enabled: !!noteId,
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
      payload: { title?: string; body?: string; group_id?: string | null };
    }) => api.patch<Note>(`/notes/${noteId}`, payload),
    onSuccess: (_data, { noteId }) => {
      qc.invalidateQueries({ queryKey: ["notes", { projectId }] });
      qc.invalidateQueries({ queryKey: ["notes", noteId] });
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
    staleTime: Infinity, // avoid re-triggering an LLM call just because the query remounted
    retry: false,
  });
}

export function useEdgeSummary(projectId: string | undefined, source: string | undefined, target: string | undefined) {
  return useQuery({
    queryKey: ["graph-summary", "edge", projectId, source, target],
    queryFn: () => api.get<GraphSummary>(`/projects/${projectId}/graph/edges/summary?source=${source}&target=${target}`),
    enabled: !!projectId && !!source && !!target,
    staleTime: Infinity,
    retry: false,
  });
}

export function useRebuildGraph(projectId: string | undefined) {
  return useMutation({
    mutationFn: () => api.post(`/projects/${projectId}/graph/rebuild`, {}),
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

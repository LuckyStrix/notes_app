export type GraphStatus = "ready" | "processing" | "error";
export type SummaryGenerationStatus = "idle" | "processing" | "ready" | "error";

export interface Project {
  id: string;
  name: string;
  description: string | null;
  rag_top_k: number | null;
  rag_similarity_floor: number | null;
  position: number;
  graph_status: GraphStatus;
  graph_error: string | null;
  graph_updated_at: string | null;
  summary_generation_status: SummaryGenerationStatus;
  summary_generation_error: string | null;
  summary_generation_progress: number;
  summary_generation_total: number;
  created_at: string;
  updated_at: string;
}

export interface Group {
  id: string;
  project_id: string;
  parent_group_id: string | null;
  name: string;
  created_at: string;
}

export type NoteType = "text" | "audio" | "video" | "document";
export type NoteStatus = "pending" | "processing" | "ready" | "error";

export interface Note {
  id: string;
  project_id: string;
  group_id: string | null;
  type: NoteType;
  title: string;
  body: string | null;
  summary: string | null;
  status: NoteStatus;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

export interface NoteVersion {
  id: string;
  title: string;
  body: string | null;
  created_at: string;
}

export type CandidateStatus = "processing" | "ready" | "error" | null;

export interface NoteFile {
  id: string;
  note_id: string;
  original_filename: string | null;
  mime_type: string | null;
  duration_seconds: number | null;
  size_bytes: number | null;
  candidate_status: CandidateStatus;
  candidate_error: string | null;
  candidates_generated_at: string | null;
}

export interface DiagramCandidate {
  id: string;
  note_id: string;
  source_page: number | null;
  source_timestamp: number | null;
  ordinal: number;
}

export interface Diagram {
  id: string;
  note_id: string;
  source_page: number | null;
  source_timestamp: number | null;
  ocr_text: string | null;
  caption: string | null;
  status: "processing" | "ready" | "error";
  error_message: string | null;
  created_at: string;
}

export interface TranscriptSegment {
  id: string;
  segment_index: number;
  start_time: number;
  end_time: number;
  text: string;
  words: { word: string; start: number; end: number; confidence: number }[] | null;
}

export interface Transcript {
  id: string;
  note_id: string;
  full_text: string | null;
  language: string | null;
  whisper_model: string | null;
  segments: TranscriptSegment[];
}

export interface GraphNode {
  id: string;
  label: string;
  significance: number;
  note_count: number;
}

export interface GraphEdge {
  source: string;
  target: string;
  significance: number;
  cooccurrence_count: number;
}

export type SummaryTier = "quality" | "basic" | null;

export interface GraphSummary {
  title: string;
  content: string | null;
  citations: Citation[];
  tier: SummaryTier;
  generated_at: string | null;
}

export interface Graph {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface ChatSession {
  id: string;
  project_id: string | null;
  title: string | null;
  created_at: string;
}

export interface Citation {
  ordinal: number;
  note_id: string;
  chunk_id?: string | null;
  diagram_id?: string | null;
  note_title?: string;
  start_time: number | null;
  end_time: number | null;
  page_start: number | null;
  page_end: number | null;
  confidence: "high" | "medium" | "low" | null;
  quote: string | null;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  created_at: string;
  citations: Citation[];
}

export interface SearchResult {
  note_id: string;
  title: string;
  type: NoteType;
  group_id: string | null;
  snippet: string;
  score: number;
}

export interface AppSettings {
  app_name: string | null;
  llm_provider: "ollama" | "anthropic";
  ollama_chat_model: string;
  ollama_fast_model: string | null;
  anthropic_chat_model: string;
  has_anthropic_api_key: boolean;
  embedding_model: string;
  ollama_vision_model: string | null;
  whisper_model: string;
  whisper_language: string;
  whisper_idle_unload_seconds: number;
  default_rag_top_k: number;
  default_rag_similarity_floor: number;
  num_ctx: number;
  updated_at: string;
}

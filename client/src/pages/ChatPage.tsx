import { useEffect, useRef, useState, type FormEvent } from "react";
import { useParams } from "react-router-dom";

import { streamChatMessage } from "../api/chatStream";
import {
  useChatMessages,
  useChatSessions,
  useCreateChatSession,
  useGroups,
  useSummarizeResetSession,
} from "../api/hooks";
import type { Citation, Group } from "../api/types";
import CitationLink from "../components/chat/CitationLink";

interface DisplayMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations: Citation[];
}

const CONTEXT_WARNING_TOKENS = 2500; // rough char/4 proxy -- see chunking.py's ~0.75 words/token comment.
// No explicit num_ctx override exists anywhere in server/app/llm/, so this is a conservative
// starting point, not a measured budget -- check `ollama show <model>` on the host to tune it.

function formatSessionLabel(session: { title: string | null; created_at: string }): string {
  if (session.title) return session.title;
  return new Date(session.created_at).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function flattenGroups(groups: Group[] | undefined): { id: string; label: string }[] {
  if (!groups) return [];
  const byParent = new Map<string | null, Group[]>();
  for (const g of groups) {
    const list = byParent.get(g.parent_group_id) ?? [];
    list.push(g);
    byParent.set(g.parent_group_id, list);
  }
  const out: { id: string; label: string }[] = [];
  function walk(parentId: string | null, depth: number) {
    const children = [...(byParent.get(parentId) ?? [])].sort((a, b) => a.name.localeCompare(b.name));
    for (const g of children) {
      out.push({ id: g.id, label: `${"— ".repeat(depth)}${g.name}` });
      walk(g.id, depth + 1);
    }
  }
  walk(null, 0);
  return out;
}

export default function ChatPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const { data: sessions } = useChatSessions(projectId);
  const { data: groups } = useGroups(projectId);
  const createSession = useCreateChatSession(projectId);
  const summarizeReset = useSummarizeResetSession(projectId);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const { data: history } = useChatMessages(sessionId ?? undefined);

  const [messages, setMessages] = useState<DisplayMessage[]>([]);
  const [input, setInput] = useState("");
  const [groupId, setGroupId] = useState<string | null>(null);
  const [streaming, setStreaming] = useState(false);
  const [warningDismissed, setWarningDismissed] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (sessions && sessions.length > 0 && !sessionId) setSessionId(sessions[0].id);
  }, [sessions, sessionId]);

  useEffect(() => {
    if (history) setMessages(history.map((m) => ({ id: m.id, role: m.role, content: m.content, citations: m.citations })));
  }, [history]);

  useEffect(() => {
    setWarningDismissed(false);
  }, [sessionId]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function ensureSession(): Promise<string> {
    if (sessionId) return sessionId;
    const session = await createSession.mutateAsync();
    setSessionId(session.id);
    return session.id;
  }

  async function newChat() {
    const session = await createSession.mutateAsync();
    setSessionId(session.id);
    setMessages([]);
  }

  async function resetFromSummary() {
    if (!sessionId) return;
    const session = await summarizeReset.mutateAsync(sessionId);
    setSessionId(session.id);
  }

  async function send(e: FormEvent) {
    e.preventDefault();
    const text = input.trim();
    if (!text || streaming) return;
    setInput("");
    const id = await ensureSession();

    setMessages((m) => [...m, { id: `u-${Date.now()}`, role: "user", content: text, citations: [] }]);
    const assistantId = `a-${Date.now()}`;
    setMessages((m) => [...m, { id: assistantId, role: "assistant", content: "", citations: [] }]);
    setStreaming(true);

    await streamChatMessage(id, text, groupId, {
      onToken: (chunk) =>
        setMessages((m) => m.map((msg) => (msg.id === assistantId ? { ...msg, content: msg.content + chunk } : msg))),
      onCitations: (citations) =>
        setMessages((m) => m.map((msg) => (msg.id === assistantId ? { ...msg, citations } : msg))),
      onError: (err) =>
        setMessages((m) =>
          m.map((msg) => (msg.id === assistantId ? { ...msg, content: msg.content + `\n\n⚠️ ${err}` } : msg)),
        ),
      onDone: () => setStreaming(false),
    });
  }

  if (!projectId) return null;

  const estTokens = messages.reduce((sum, m) => sum + m.content.length, 0) / 4;
  const showWarning = estTokens > CONTEXT_WARNING_TOKENS && !warningDismissed;
  const flatGroups = flattenGroups(groups);

  return (
    <div className="page chat-page">
      <h1>Chat</h1>
      <p className="muted">Ask questions about the notes in this project — answers cite their sources.</p>

      <div className="form-inline" style={{ marginBottom: "0.75rem" }}>
        <select value={sessionId ?? ""} onChange={(e) => setSessionId(e.target.value || null)}>
          {!sessions?.length && <option value="">New chat</option>}
          {sessions?.map((s) => (
            <option key={s.id} value={s.id}>
              {formatSessionLabel(s)}
            </option>
          ))}
        </select>
        <button type="button" onClick={newChat} disabled={createSession.isPending}>
          New chat
        </button>
        <select value={groupId ?? ""} onChange={(e) => setGroupId(e.target.value || null)}>
          <option value="">All notes</option>
          {flatGroups.map((g) => (
            <option key={g.id} value={g.id}>
              {g.label}
            </option>
          ))}
        </select>
      </div>

      {showWarning && (
        <div className="card" style={{ borderColor: "var(--accent)", marginBottom: "0.75rem" }}>
          <p style={{ margin: 0 }}>
            This conversation is getting long — older messages will keep being resent in full to the model on every
            turn, which slows things down and can eventually exceed its context window.
          </p>
          <div className="form-inline" style={{ marginTop: "0.5rem" }}>
            <button type="button" onClick={newChat}>New chat</button>
            <button type="button" onClick={resetFromSummary} disabled={summarizeReset.isPending}>
              {summarizeReset.isPending ? "Summarizing…" : "Reset from summary"}
            </button>
            <button type="button" className="icon-btn" onClick={() => setWarningDismissed(true)}>Dismiss</button>
          </div>
        </div>
      )}

      <div className="chat-messages">
        {messages.length === 0 && <p className="muted">No messages yet. Ask something below.</p>}
        {messages.map((m) => (
          <div key={m.id} className={`chat-message chat-${m.role}`}>
            <p style={{ whiteSpace: "pre-wrap", margin: 0 }}>
              {m.content || (streaming && m.role === "assistant" ? "…" : "")}
            </p>
            {m.citations.length > 0 && (
              <div className="citation-list">
                {m.citations.map((c) => (
                  <CitationLink key={c.ordinal} projectId={projectId} citation={c} />
                ))}
              </div>
            )}
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      <form className="form-inline" onSubmit={send}>
        <input
          placeholder="Ask about your notes…"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          disabled={streaming}
        />
        <button type="submit" disabled={streaming || !input.trim()}>Send</button>
      </form>
    </div>
  );
}

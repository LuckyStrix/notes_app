import type { Citation } from "./types";

interface StreamHandlers {
  onToken: (text: string) => void;
  onCitations: (citations: Citation[]) => void;
  onError?: (message: string) => void;
  onDone?: () => void;
}

export async function streamChatMessage(
  sessionId: string,
  content: string,
  groupId: string | null,
  handlers: StreamHandlers,
): Promise<void> {
  const res = await fetch(`/api/chat/sessions/${sessionId}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content, group_id: groupId }),
  });
  if (!res.ok || !res.body) {
    handlers.onError?.(`${res.status} ${await res.text().catch(() => res.statusText)}`);
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let sepIndex: number;
    while ((sepIndex = buffer.indexOf("\n\n")) !== -1) {
      const rawEvent = buffer.slice(0, sepIndex);
      buffer = buffer.slice(sepIndex + 2);
      processEvent(rawEvent, handlers);
    }
  }
  handlers.onDone?.();
}

function processEvent(rawEvent: string, handlers: StreamHandlers) {
  let eventType = "message";
  let data = "";
  for (const line of rawEvent.split("\n")) {
    if (line.startsWith("event:")) eventType = line.slice(6).trim();
    else if (line.startsWith("data:")) data += line.slice(5).trim();
  }
  if (!data) return;

  const parsed = JSON.parse(data);
  if (eventType === "token") handlers.onToken(parsed as string);
  else if (eventType === "citations") handlers.onCitations(parsed as Citation[]);
  else if (eventType === "error") handlers.onError?.(parsed as string);
}

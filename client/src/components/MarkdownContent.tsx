import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

// Shared renderer for AI-generated text (chat messages, graph summaries).
// No rehype-raw -- content is untrusted, so embedded HTML stays escaped.
export default function MarkdownContent({ content, className }: { content: string; className?: string }) {
  return (
    <div className={`markdown-content${className ? ` ${className}` : ""}`}>
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
    </div>
  );
}

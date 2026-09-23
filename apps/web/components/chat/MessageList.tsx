import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { UiMessage } from "@/lib/chat-events";

function ToolBubble({ message }: { message: Extract<UiMessage, { kind: "tool" }> }) {
  const argsPreview = Object.entries(message.arguments)
    .map(([key, value]) => `${key}=${JSON.stringify(value)}`)
    .join(", ");
  return (
    <details className="mx-auto w-full max-w-xl rounded-lg border border-border bg-sidebar px-3 py-2 text-xs text-text-secondary">
      <summary className="cursor-pointer select-none">
        🔧 {message.name}({argsPreview})
        {message.ok !== undefined && (message.ok ? " ✓" : " ✗")}
      </summary>
      {message.result !== undefined && (
        <pre className="mt-2 max-h-48 overflow-y-auto whitespace-pre-wrap break-all">{message.result}</pre>
      )}
    </details>
  );
}

export function MessageList({ messages }: { messages: UiMessage[] }) {
  return (
    <ol className="flex flex-1 flex-col gap-3 overflow-y-auto px-4 py-6">
      {messages.map((message) => {
        if (message.kind === "user") {
          return (
            <li key={message.id} className="max-w-[75%] self-end rounded-2xl bg-user-bubble px-4 py-2 text-sm text-white">
              {message.content}
            </li>
          );
        }
        if (message.kind === "assistant") {
          return (
            <li key={message.id} className="max-w-[85%] self-start text-sm leading-6">
              <div className="md">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown>
              </div>
              {message.streaming && <span className="animate-pulse text-text-secondary">▍</span>}
            </li>
          );
        }
        if (message.kind === "tool") {
          return <li key={message.id}><ToolBubble message={message} /></li>;
        }
        return (
          <li key={message.id} className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-600">
            出错了：{message.content}
          </li>
        );
      })}
    </ol>
  );
}

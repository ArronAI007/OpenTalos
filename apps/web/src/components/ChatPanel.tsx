import { useEffect, useRef, useState, type ChangeEvent, type FormEvent, type KeyboardEvent } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { ChatMessage, OutgoingChatMessage, RunStatus } from "../types.js";
import {
  formatTextAttachment,
  isImageFile,
  isTextFile,
  MAX_IMAGES_PER_MESSAGE,
  MAX_IMAGE_FILE_BYTES,
  MAX_TEXT_FILE_BYTES,
  readFileAsDataUrl,
  readFileAsText,
  type PendingAttachment,
} from "../lib/attachments.js";

/** Assistant replies render as Markdown (headings/lists/code/tables/etc. from the model come
 * through formatted instead of as literal `**`/`#`/backtick characters); user messages stay plain
 * text — it's what the user actually typed, not something meant to be interpreted as markup.
 * react-markdown never renders raw HTML unless rehype-raw is added (it isn't here), so this is
 * safe against the model's own output regardless of what it contains. */
function AssistantMarkdown({ text }: { text: string }) {
  return (
    <div className="markdown-body">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
    </div>
  );
}

/** Collapsible block for a model's reasoning/thinking trace. Expanded by default only while
 * `isThinking` is true (the model is actively producing reasoning and hasn't started its final
 * answer yet); auto-collapses the moment `isThinking` flips to false, mirroring how it behaves for
 * an already-completed historical message (`isThinking` is always false there, so it starts
 * collapsed). The user can still manually re-expand afterward — that choice is never overridden. */
function ReasoningBlock({ text, isThinking }: { text: string; isThinking: boolean }) {
  const [expanded, setExpanded] = useState(isThinking);
  const wasThinking = useRef(isThinking);
  useEffect(() => {
    if (wasThinking.current && !isThinking) {
      setExpanded(false);
    }
    wasThinking.current = isThinking;
  }, [isThinking]);

  return (
    <div className="reasoning-block">
      <button
        type="button"
        className="reasoning-toggle"
        onClick={() => setExpanded((value) => !value)}
        aria-expanded={expanded}
      >
        {isThinking ? "⚙ 思考中…" : expanded ? "▾ 思考过程" : "▸ 已完成思考"}
      </button>
      {expanded && <p className="reasoning-content">{text}</p>}
    </div>
  );
}

/** Read-only thumbnail grid for a message's attached images — used both for a historical
 * ChatMessage and for the live streaming bubble is NOT needed here, since only the user ever
 * attaches images (the model doesn't send any back). */
function MessageImages({ images }: { images: string[] }) {
  return (
    <div className="message-images">
      {images.map((src, index) => (
        <img key={index} src={src} alt="用户上传的图片附件" className="message-image" />
      ))}
    </div>
  );
}

/** Read-only, labeled code block for a message's attached text/code files — kept separate from
 * `AssistantMarkdown`'s markdown rendering (user messages are intentionally never markdown-parsed,
 * see that component's own comment) and from plain `message.text`, so a file's raw content never
 * shows up as literal ``` characters in the middle of a plain-text bubble. */
function TextAttachmentBlock({ name, content }: { name: string; content: string }) {
  return (
    <div className="text-attachment-block">
      <p className="text-attachment-name">📄 {name}</p>
      <pre className="text-attachment-content">{content}</pre>
    </div>
  );
}

interface ChatPanelProps {
  messages: ChatMessage[];
  onSend: (message: OutgoingChatMessage) => void;
  onStop?: () => void;
  error?: string;
  disabled?: boolean;
  /** The run's actual status. Required (in addition to `disabled`/`streamingText`) to gate the
   * stop control: a paused-for-approval run is also `disabled` and can still have leftover
   * `streamingText` from before the pause (nothing clears it on pause), so without this the stop
   * button would stay visible/clickable through the entire HITL approval wait — a phase the
   * cancellation feature explicitly does not apply to. */
  status?: RunStatus;
  /** The assistant's reply so far, while it's still streaming in. Rendered as a trailing bubble
   * after `messages` until the real ChatMessage is appended once the run finishes. */
  streamingText?: string;
  /** The model's reasoning/thinking trace so far, while it's still streaming in — see
   * ReasoningBlock. Empty/undefined for turns (or models) that never produce one. */
  reasoningStreamingText?: string;
  /** Resolves the pending HITL pause (see graph.ts's `confirm` node) when `status === "paused"`.
   * Mirrors TracePanel's onApprove — the same run can be approved/rejected from either place. */
  onApprove?: (approved: boolean) => void;
  /** Set briefly after a steering message is accepted (see App.tsx's handleSteer) — cleared once
   * the model actually starts streaming a fresh reply. Shown as a small confirmation near the
   * composer status line so the user knows their mid-reply message was received. */
  steerConfirmation?: string;
}

export function ChatPanel({
  messages,
  onSend,
  onStop,
  error,
  disabled,
  status,
  streamingText,
  reasoningStreamingText,
  onApprove,
  steerConfirmation,
}: ChatPanelProps) {
  const [draft, setDraft] = useState("");
  const [pendingAttachments, setPendingAttachments] = useState<PendingAttachment[]>([]);
  const [attachmentError, setAttachmentError] = useState<string>();
  const bottomRef = useRef<HTMLLIElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Same double-click/double-tap guard as TracePanel's approval buttons (see its comment for why
  // a ref is required in addition to the state): reset whenever a NEW pause starts, not just once.
  const hasRespondedRef = useRef(false);
  const [hasResponded, setHasResponded] = useState(false);
  useEffect(() => {
    if (status === "paused") {
      hasRespondedRef.current = false;
      setHasResponded(false);
    }
  }, [status]);

  function handleApprove(approved: boolean) {
    if (hasRespondedRef.current) return;
    hasRespondedRef.current = true;
    setHasResponded(true);
    onApprove?.(approved);
  }

  // message-list scrolls independently of the page now (app.css pins the composer below it), so
  // without this a new message or an in-progress stream would land below the visible fold instead
  // of the composer following it down.
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end" });
  }, [messages, streamingText, reasoningStreamingText]);

  async function handleFilesSelected(event: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(event.target.files ?? []);
    // Cleared immediately (not after processing) so selecting the exact same file again still
    // fires onChange next time — the browser otherwise treats an unchanged file list as a no-op.
    event.target.value = "";
    if (files.length === 0) return;

    setAttachmentError(undefined);
    const currentImageCount = pendingAttachments.filter((a) => a.kind === "image").length;
    let imageCount = currentImageCount;
    const accepted: PendingAttachment[] = [];

    for (const file of files) {
      if (isImageFile(file)) {
        if (imageCount >= MAX_IMAGES_PER_MESSAGE) {
          setAttachmentError(`最多只能附加 ${MAX_IMAGES_PER_MESSAGE} 张图片`);
          continue;
        }
        if (file.size > MAX_IMAGE_FILE_BYTES) {
          setAttachmentError(`"${file.name}" 超过 ${Math.floor(MAX_IMAGE_FILE_BYTES / (1024 * 1024))}MB 限制`);
          continue;
        }
        try {
          const dataUrl = await readFileAsDataUrl(file);
          accepted.push({ id: crypto.randomUUID(), name: file.name, size: file.size, kind: "image", dataUrl });
          imageCount += 1;
        } catch {
          setAttachmentError(`读取 "${file.name}" 失败，请重试`);
        }
        continue;
      }
      if (isTextFile(file)) {
        if (file.size > MAX_TEXT_FILE_BYTES) {
          setAttachmentError(`"${file.name}" 超过 ${Math.floor(MAX_TEXT_FILE_BYTES / 1024)}KB 限制`);
          continue;
        }
        try {
          const textContent = await readFileAsText(file);
          accepted.push({ id: crypto.randomUUID(), name: file.name, size: file.size, kind: "text", textContent });
        } catch {
          setAttachmentError(`读取 "${file.name}" 失败，请重试`);
        }
        continue;
      }
      setAttachmentError(`不支持的文件类型："${file.name}"，仅支持图片和文本/代码文件`);
    }

    if (accepted.length > 0) {
      setPendingAttachments((prev) => [...prev, ...accepted]);
    }
  }

  function removeAttachment(id: string) {
    setPendingAttachments((prev) => prev.filter((attachment) => attachment.id !== id));
  }

  function attachmentPlaceholderText(): string {
    const hasImages = pendingAttachments.some((a) => a.kind === "image");
    const hasText = pendingAttachments.some((a) => a.kind === "text");
    if (hasImages && hasText) return "[图片和附件]";
    return hasImages ? "[图片]" : "[附件]";
  }

  function submit() {
    if (disabled) return;
    const trimmed = draft.trim();
    if (!trimmed && pendingAttachments.length === 0) return;
    const images = pendingAttachments.filter((a) => a.kind === "image").map((a) => a.dataUrl!);
    const textAttachments = pendingAttachments
      .filter((a) => a.kind === "text")
      .map((a) => ({ name: a.name, content: a.textContent! }));
    const displayText = trimmed || attachmentPlaceholderText();
    // The model has no separate channel for attachment content — this project deliberately has no
    // attachment storage layer of its own — so it's inlined into the text actually sent, even
    // though the LOCAL display keeps it out of displayText (see TextAttachmentBlock).
    const modelText =
      displayText + textAttachments.map((a) => formatTextAttachment(a.name, a.content)).join("");
    onSend({
      modelText,
      displayText,
      images: images.length > 0 ? images : undefined,
      textAttachments: textAttachments.length > 0 ? textAttachments : undefined,
    });
    setDraft("");
    setPendingAttachments([]);
    setAttachmentError(undefined);
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    submit();
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    // Pressing Enter to confirm an IME composition (e.g. selecting a candidate while typing
    // Chinese/Japanese/Korean pinyin/kana) must fill that text into the textarea, not submit it.
    // `isComposing` covers most browsers; `keyCode === 229` is Safari's documented way of marking
    // the composition-ending keydown even once `isComposing` has already flipped back to false by
    // the time this handler runs.
    if (event.nativeEvent.isComposing || event.keyCode === 229) return;
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      submit();
    }
  }

  const isStreaming = status === "running" && streamingText !== undefined && streamingText.length > 0;

  return (
    <section className="chat-panel" aria-label="对话">
      {messages.length === 0 && !streamingText && !reasoningStreamingText ? (
        <div className="chat-empty">
          <p className="chat-empty-title">开始对话</p>
          <p className="chat-empty-subtitle">在下方输入框输入消息开始对话</p>
        </div>
      ) : (
        <ul className="message-list">
          {messages.map((message) => (
            <li key={message.id} className={`message message-${message.role}`}>
              {message.role === "assistant" && message.reasoningText && (
                <ReasoningBlock text={message.reasoningText} isThinking={false} />
              )}
              {message.images && message.images.length > 0 && <MessageImages images={message.images} />}
              {message.role === "assistant" ? <AssistantMarkdown text={message.text} /> : message.text}
              {message.textAttachments?.map((attachment) => (
                <TextAttachmentBlock key={attachment.name} name={attachment.name} content={attachment.content} />
              ))}
            </li>
          ))}
          {(streamingText || reasoningStreamingText) && (
            <li className={`message message-assistant${status === "paused" ? "" : " message-streaming"}`}>
              {reasoningStreamingText && (
                <ReasoningBlock
                  text={reasoningStreamingText}
                  isThinking={status === "running" && !streamingText}
                />
              )}
              {streamingText && (
                <>
                  <AssistantMarkdown text={streamingText} />
                  {/* Generation is actually finished once paused for approval — a blinking cursor
                   * here would falsely suggest the model is still writing. */}
                  {status !== "paused" && <span className="streaming-cursor" aria-hidden="true" />}
                </>
              )}
            </li>
          )}
          {status === "paused" && (
            <li className="chat-approval">
              <p>⏸ 这条回复调用了工具，是否发送给你？</p>
              <div className="chat-approval-actions">
                <button className="approve-button" onClick={() => handleApprove(true)} disabled={hasResponded}>
                  ✓ 批准
                </button>
                <button className="deny-button" onClick={() => handleApprove(false)} disabled={hasResponded}>
                  ✕ 拒绝
                </button>
              </div>
            </li>
          )}
          <li ref={bottomRef} className="message-list-end" aria-hidden="true" />
        </ul>
      )}
      {error && <p className="chat-error">{error}</p>}
      {attachmentError && <p className="chat-error">{attachmentError}</p>}
      {pendingAttachments.length > 0 && (
        <ul className="attachment-preview-list">
          {pendingAttachments.map((attachment) => (
            <li key={attachment.id} className="attachment-chip">
              {attachment.kind === "image" ? (
                <img src={attachment.dataUrl} alt={attachment.name} className="attachment-chip-thumb" />
              ) : (
                <span className="attachment-chip-icon" aria-hidden="true">
                  📄
                </span>
              )}
              <span className="attachment-chip-name">{attachment.name}</span>
              <button
                type="button"
                className="attachment-chip-remove"
                onClick={() => removeAttachment(attachment.id)}
                aria-label={`移除附件 ${attachment.name}`}
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      )}
      <form className="composer" onSubmit={handleSubmit}>
        <textarea
          className="composer-input"
          placeholder="给智能体发消息"
          rows={1}
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={handleKeyDown}
          disabled={disabled}
        />
        <div className="composer-toolbar">
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept="image/*,.txt,.md,.py,.js,.jsx,.ts,.tsx,.json,.csv,.yaml,.yml,.html,.css,.sh,.sql,.java,.go,.rs,.c,.cpp,.h,.rb,.php"
            onChange={handleFilesSelected}
            hidden
          />
          <button
            type="button"
            className="composer-attach"
            onClick={() => fileInputRef.current?.click()}
            disabled={disabled}
            aria-label="添加附件"
          >
            <svg viewBox="0 0 24 24" width="18" height="18" fill="none" aria-hidden="true">
              <path d="M12 5V19M5 12H19" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
            </svg>
          </button>
          {isStreaming && !draft.trim() && pendingAttachments.length === 0 ? (
            // Only show Stop (which cancels the whole run) while the composer is empty. The
            // moment the user has something to send, switch to Send — while streaming, that
            // steers the reply (see App.tsx's handleSteer) rather than cancelling it, so a
            // user acting on "可发送以调整方向" must see Send, not Stop, as their next click.
            <button type="button" className="composer-stop" onClick={onStop} aria-label="停止">
              <svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor" aria-hidden="true">
                <rect x="5" y="5" width="14" height="14" rx="2" />
              </svg>
            </button>
          ) : (
            <button
              className="composer-send"
              type="submit"
              disabled={disabled || (!draft.trim() && pendingAttachments.length === 0)}
              aria-label="发送"
            >
              <svg viewBox="0 0 24 24" width="16" height="16" fill="none" aria-hidden="true">
                <path
                  d="M3 11.5L20.5 3.5L14.5 21L11 13L3 11.5Z"
                  stroke="currentColor"
                  strokeWidth="1.6"
                  strokeLinejoin="round"
                  strokeLinecap="round"
                />
              </svg>
            </button>
          )}
        </div>
      </form>
      {steerConfirmation && <p className="composer-status composer-status-steer">{steerConfirmation}</p>}
      <p className="composer-status">
        {status === "paused" ? "等待你确认" : status === "running" ? "运行中…（可发送以调整方向）" : "准备就绪"}
      </p>
    </section>
  );
}

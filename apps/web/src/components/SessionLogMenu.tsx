import { useEffect, useRef, useState } from "react";
import type { ChatSession } from "../types.js";
import { sessionTitle } from "../lib/sessions.js";
import { ChevronDownIcon, DownloadIcon } from "./icons.js";

interface SessionLogMenuProps {
  session: ChatSession;
}

function downloadFile(filename: string, content: string, mime: string): void {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

function sessionAsText(session: ChatSession): string {
  return session.messages.map((message) => `[${message.role}] ${message.text}`).join("\n\n");
}

export function SessionLogMenu({ session }: SessionLogMenuProps) {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function handlePointerDown(event: PointerEvent) {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) setOpen(false);
    }
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    document.addEventListener("pointerdown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [open]);

  const title = sessionTitle(session);

  return (
    <div className="session-log-menu" ref={containerRef}>
      <button
        type="button"
        className="session-log-trigger"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        aria-haspopup="menu"
      >
        <DownloadIcon />
        Session log
        <ChevronDownIcon />
      </button>
      {open && (
        <ul className="session-log-dropdown" role="menu">
          <li role="none">
            <button
              type="button"
              role="menuitem"
              onClick={() => {
                downloadFile(`${title}.json`, JSON.stringify(session, null, 2), "application/json");
                setOpen(false);
              }}
            >
              导出为 JSON
            </button>
          </li>
          <li role="none">
            <button
              type="button"
              role="menuitem"
              onClick={() => {
                downloadFile(`${title}.txt`, sessionAsText(session), "text/plain");
                setOpen(false);
              }}
            >
              导出为文本
            </button>
          </li>
        </ul>
      )}
    </div>
  );
}

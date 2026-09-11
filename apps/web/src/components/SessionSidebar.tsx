import type { ChatSession } from "../types.js";
import { sessionTitle } from "../lib/sessions.js";

interface SessionSidebarProps {
  sessions: ChatSession[];
  activeSessionId: string;
  open: boolean;
  onSelect: (id: string) => void;
  onCreate: () => void;
  onDelete: (id: string) => void;
  onClose: () => void;
}

export function SessionSidebar({ sessions, activeSessionId, open, onSelect, onCreate, onDelete, onClose }: SessionSidebarProps) {
  return (
    <>
      {/* Only visible (via CSS, at narrow widths) while the sidebar is open as a slide-in drawer;
          harmless on wide layouts where the sidebar is always docked. */}
      {open && <button type="button" className="sidebar-scrim" aria-label="关闭会话列表" onClick={onClose} />}
      {/* No aria-hidden here: unlike the trace drawer, this sidebar is permanently docked (and
          fully interactive) on wide viewports — `open` only toggles its narrow-viewport slide-in
          behavior via CSS, so tying aria-hidden to it would incorrectly hide the always-visible
          desktop sidebar from assistive tech whenever `open` happened to be false. */}
      <nav className={`session-sidebar${open ? " session-sidebar-open" : ""}`} aria-label="会话列表">
        <button type="button" className="session-new-button" onClick={onCreate}>
          + 新对话
        </button>
        <ul className="session-list">
          {sessions.map((session) => {
            const title = sessionTitle(session);
            const isActive = session.id === activeSessionId;
            return (
              <li key={session.id} className="session-item">
                <button
                  type="button"
                  className={`session-button${isActive ? " session-button-active" : ""}`}
                  aria-current={isActive || undefined}
                  onClick={() => onSelect(session.id)}
                  title={title}
                >
                  {title}
                </button>
                {sessions.length > 1 && (
                  <button
                    type="button"
                    className="session-delete-button"
                    aria-label={`删除会话 ${title}`}
                    onClick={(event) => {
                      event.stopPropagation();
                      onDelete(session.id);
                    }}
                  >
                    ✕
                  </button>
                )}
              </li>
            );
          })}
        </ul>
      </nav>
    </>
  );
}

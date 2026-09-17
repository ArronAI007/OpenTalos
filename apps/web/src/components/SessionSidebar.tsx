import { useState, type CSSProperties } from "react";
import type { ChatSession } from "../types.js";
import { relativeSessionAge, sessionTitle } from "../lib/sessions.js";
import { clampSidebarWidth } from "../lib/sidebar-width.js";
import { CollapseIcon, GearIcon, PlusIcon, SearchIcon, SortIcon } from "./icons.js";

interface SessionSidebarProps {
  sessions: ChatSession[];
  activeSessionId: string;
  open: boolean;
  collapsed: boolean;
  /** Current sidebar width in px (ignored while `collapsed` — the collapsed rail has its own
   * fixed width, see .session-sidebar-collapsed). */
  width: number;
  /** Fired continuously while the user drags the resize handle, with the new (already-clamped)
   * width — the caller owns persisting it (see App.tsx's loadSidebarWidth/saveSidebarWidth). */
  onWidthChange: (width: number) => void;
  onSelect: (id: string) => void;
  onCreate: () => void;
  onDelete: (id: string) => void;
  onClose: () => void;
  onToggleCollapse: () => void;
  onOpenSettings: () => void;
}

export function SessionSidebar({
  sessions,
  activeSessionId,
  open,
  collapsed,
  width,
  onWidthChange,
  onSelect,
  onCreate,
  onDelete,
  onClose,
  onToggleCollapse,
  onOpenSettings,
}: SessionSidebarProps) {
  const [searchOpen, setSearchOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [oldestFirst, setOldestFirst] = useState(false);

  // Plain document-level pointermove/pointerup listeners (added/removed per drag) rather than
  // React state + a render-driven effect: a resize needs to track the pointer at native event
  // speed without waiting on React's render cycle, and the listeners' own lifetime is already
  // exactly one drag gesture, so there's nothing for React to additionally own here.
  function handleResizeStart(event: React.PointerEvent<HTMLDivElement>) {
    // Only the primary button/touch starts a resize — ignore right-click, middle-click, etc.
    if (event.button !== 0) return;
    event.preventDefault();
    const startX = event.clientX;
    const startWidth = width;
    const previousCursor = document.body.style.cursor;
    const previousUserSelect = document.body.style.userSelect;
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
    // .session-sidebar's own `transition: width ...` (for the collapse/expand animation) would
    // otherwise ease the width toward each new value instead of tracking the pointer 1:1, making
    // the drag feel laggy — suspend it only for the duration of this drag gesture.
    const sidebarEl = (event.currentTarget as HTMLElement).closest(".session-sidebar");
    sidebarEl?.classList.add("session-sidebar-resizing");

    function handlePointerMove(moveEvent: PointerEvent) {
      onWidthChange(clampSidebarWidth(startWidth + (moveEvent.clientX - startX)));
    }
    function handlePointerUp() {
      document.removeEventListener("pointermove", handlePointerMove);
      document.removeEventListener("pointerup", handlePointerUp);
      document.body.style.cursor = previousCursor;
      document.body.style.userSelect = previousUserSelect;
      sidebarEl?.classList.remove("session-sidebar-resizing");
    }
    document.addEventListener("pointermove", handlePointerMove);
    document.addEventListener("pointerup", handlePointerUp);
  }

  const filtered = sessions.filter((session) => sessionTitle(session).toLowerCase().includes(query.toLowerCase()));
  const visibleSessions = oldestFirst ? [...filtered].reverse() : filtered;

  return (
    <>
      {/* Only visible (via CSS, at narrow widths) while the sidebar is open as a slide-in drawer;
          harmless on wide layouts where the sidebar is always docked. */}
      {open && <button type="button" className="sidebar-scrim" aria-label="关闭会话列表" onClick={onClose} />}
      {/* No aria-hidden here: unlike a true overlay drawer, this sidebar is permanently docked
          (and fully interactive) on wide viewports — `open` only toggles its narrow-viewport
          slide-in behavior via CSS, so tying aria-hidden to it would incorrectly hide the
          always-visible desktop sidebar from assistive tech whenever `open` happened to be
          false. */}
      <nav
        className={`session-sidebar${open ? " session-sidebar-open" : ""}${collapsed ? " session-sidebar-collapsed" : ""}`}
        // Set as a custom property, not the `width` property directly: .session-sidebar-collapsed
        // and the narrow-viewport drawer media query both need to keep overriding the width via
        // an ordinary CSS rule (see app.css) -- an inline `width` would out-rank both regardless
        // of specificity, but an inline custom property doesn't touch `width`'s cascade at all.
        style={collapsed ? undefined : ({ "--sidebar-width": `${width}px` } as CSSProperties)}
        aria-label="会话列表"
      >
        {!collapsed && (
          <div
            className="sidebar-resize-handle"
            onPointerDown={handleResizeStart}
            role="separator"
            aria-orientation="vertical"
            aria-label="调整会话列表宽度"
          />
        )}
        {collapsed ? (
          // Collapsing shrinks the sidebar to a slim rail rather than hiding it entirely, so the
          // control that re-expands it stays where a user would look for it — inside the sidebar's
          // own column — instead of migrating into the main header next to the title.
          <div className="sidebar-rail">
            <span className="sidebar-brand-mark" aria-hidden="true">
              OT
            </span>
            <button
              type="button"
              className="sidebar-icon-button sidebar-expand-button"
              onClick={onToggleCollapse}
              aria-label="展开侧栏"
            >
              <CollapseIcon />
            </button>
          </div>
        ) : (
          <>
            <div className="sidebar-brand">
              <span className="sidebar-brand-mark" aria-hidden="true">
                OT
              </span>
              <span className="sidebar-brand-name">OpenTalos</span>
              <button
                type="button"
                className="sidebar-icon-button sidebar-collapse-button"
                onClick={onToggleCollapse}
                aria-label="收起侧栏"
              >
                <CollapseIcon />
              </button>
            </div>
            <button type="button" className="session-new-button" onClick={onCreate}>
              + 新会话
            </button>
            <div className="sidebar-workspace-row">
              <span className="sidebar-workspace-label">工作区</span>
              <div className="sidebar-workspace-actions">
                <button
                  type="button"
                  className="sidebar-icon-button"
                  aria-label="搜索会话"
                  aria-pressed={searchOpen}
                  onClick={() => setSearchOpen((value) => !value)}
                >
                  <SearchIcon />
                </button>
                <button
                  type="button"
                  className="sidebar-icon-button"
                  aria-label={oldestFirst ? "按最新优先排序" : "按最早优先排序"}
                  onClick={() => setOldestFirst((value) => !value)}
                >
                  <SortIcon />
                </button>
                <button type="button" className="sidebar-icon-button" aria-label="新建会话" onClick={onCreate}>
                  <PlusIcon />
                </button>
              </div>
            </div>
            {searchOpen && (
              <input
                type="search"
                className="sidebar-search-input"
                placeholder="搜索会话"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                autoFocus
              />
            )}
            <ul className="session-list">
              {visibleSessions.length === 0 ? (
                <li className="session-empty">无匹配会话</li>
              ) : (
                visibleSessions.map((session) => {
                  const title = sessionTitle(session);
                  const isActive = session.id === activeSessionId;
                  return (
                    <li key={session.id} className="session-item">
                      <button
                        type="button"
                        className={`session-button${isActive ? " session-button-active" : ""}`}
                        aria-current={isActive || undefined}
                        aria-label={title}
                        onClick={() => onSelect(session.id)}
                        title={title}
                      >
                        <span className="session-button-title">{title}</span>
                        <span className="session-button-age">{relativeSessionAge(session.createdAt)}</span>
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
                })
              )}
            </ul>
            <button type="button" className="sidebar-settings-button" onClick={onOpenSettings}>
              <GearIcon />
              设置
            </button>
          </>
        )}
      </nav>
    </>
  );
}

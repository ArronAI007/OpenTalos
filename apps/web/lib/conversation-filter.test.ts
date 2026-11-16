import { describe, expect, test } from "vitest";

import type { Task } from "./api";
import { conversationTitle, filterConversations } from "./conversation-filter";

const task = (patch: Partial<Task>): Task => ({
  id: "1",
  title: "Task",
  agent_type: "react",
  updated_at: "2026-01-01T00:00:00",
  pinned: false,
  starred: false,
  archived: false,
  project_id: null,
  ...patch,
});

describe("conversation filters", () => {
  test("searches title and agent then pins first", () => {
    const result = filterConversations(
      [
        task({ id: "new", title: "Alpha", updated_at: "2026-02-01" }),
        task({ id: "pin", title: "Alpha report", pinned: true }),
        task({ id: "other", title: "Beta" }),
      ],
      "alpha"
    );
    expect(result.map((item) => item.id)).toEqual(["pin", "new"]);
  });

  test("uses a stable fallback title", () => {
    expect(conversationTitle(task({ title: " " }))).toBe("未命名会话");
  });
});

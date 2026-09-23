import { describe, expect, it } from "vitest";
import { API_URL, tasksUrl } from "./api";

describe("tasksUrl", () => {
  it("默认无参不拼 query", () => {
    expect(tasksUrl()).toBe(`${API_URL}/api/tasks`);
  });

  it("archived=true 拼 archived=1", () => {
    expect(tasksUrl({ archived: true })).toBe(`${API_URL}/api/tasks?archived=1`);
  });

  it("archived=false 不拼 query", () => {
    expect(tasksUrl({ archived: false })).toBe(`${API_URL}/api/tasks`);
  });
});

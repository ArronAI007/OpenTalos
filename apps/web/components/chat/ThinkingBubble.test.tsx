// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { ThinkingBubble } from "./ThinkingBubble";

describe("ThinkingBubble", () => {
  it("shows only natural-language tool actions while streaming", () => {
    render(
      <ThinkingBubble
        streaming
        items={[
          { id: "r1", kind: "reasoning", content: "运行 bash scripts/main.py 然后继续", streaming: true },
          {
            id: "t1",
            kind: "tool",
            name: "bash",
            arguments: { command: "python3 scripts/main.py" },
            result: "2026-10-12",
            ok: true,
          },
        ]}
      />,
    );

    expect(screen.getByText("正在思考…")).toBeInTheDocument();
    expect(screen.getByText("已完成：运行技能脚本")).toBeInTheDocument();
    // 不暴露原始思维链 / 命令 / 脚本路径 / 原始细节。
    expect(screen.queryByText(/scripts\/main\.py|python3|\bbash\b/)).not.toBeInTheDocument();
    expect(screen.queryByText("查看原始细节")).not.toBeInTheDocument();
  });

  it("stays expanded when settled and collapses on click", async () => {
    render(
      <ThinkingBubble
        streaming={false}
        items={[{ id: "t1", kind: "tool", name: "web_search", arguments: {}, result: "ok", ok: true }]}
      />,
    );
    const user = userEvent.setup();

    expect(screen.getByText("思考过程")).toBeInTheDocument();
    expect(screen.getByText(/网页搜索/)).toBeInTheDocument(); // 定稿后仍展开，思考过程可见

    await user.click(screen.getByRole("button"));
    expect(screen.queryByText(/网页搜索/)).not.toBeInTheDocument();
  });
});

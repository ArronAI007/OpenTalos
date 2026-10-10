// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { ThinkingBubble } from "./ThinkingBubble";

describe("ThinkingBubble", () => {
  it("shows cleaned reasoning and tool activity in one panel while streaming", () => {
    render(
      <ThinkingBubble
        streaming
        items={[
          { id: "r1", kind: "reasoning", content: "先看 ```python\nprint(1)\n``` 然后继续", streaming: true },
          { id: "t1", kind: "tool", name: "web_search", arguments: { query: "manus 招聘" }, result: "ok", ok: true },
        ]}
      />,
    );

    expect(screen.getByText("正在思考…")).toBeInTheDocument();
    expect(screen.getByText(/然后继续/)).toBeInTheDocument();
    expect(screen.queryByText(/print\(1\)/)).not.toBeInTheDocument(); // 代码围栏被清洗
    expect(screen.getByText(/已使用「网页搜索」/)).toBeInTheDocument();
  });

  it("collapses when settled and expands on click", async () => {
    render(
      <ThinkingBubble
        streaming={false}
        items={[{ id: "r1", kind: "reasoning", content: "这是一段思路", streaming: false }]}
      />,
    );
    const user = userEvent.setup();

    expect(screen.getByText("思考过程")).toBeInTheDocument();
    expect(screen.queryByText("这是一段思路")).not.toBeInTheDocument(); // 定稿后自动收起

    await user.click(screen.getByRole("button"));
    expect(screen.getByText("这是一段思路")).toBeInTheDocument();
  });
});

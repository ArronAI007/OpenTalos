// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { Composer } from "./Composer";

describe("Composer", () => {
  it("sends the trimmed text on submit", async () => {
    const onSend = vi.fn();
    render(<Composer onSend={onSend} disabled={false} />);
    const user = userEvent.setup();

    await user.type(screen.getByLabelText("输入消息"), "  hello  ");
    await user.click(screen.getByRole("button", { name: "发送" }));

    expect(onSend).toHaveBeenCalledWith("hello");
  });

  it("allows typing and steering while busy, and stop still works", async () => {
    const onSend = vi.fn();
    const onStop = vi.fn();
    render(<Composer onSend={onSend} disabled onStop={onStop} />);
    const user = userEvent.setup();

    const textarea = screen.getByLabelText("输入消息");
    expect(textarea).toBeEnabled();
    expect(screen.getByPlaceholderText("补充指令以纠偏…")).toBeInTheDocument();

    await user.type(textarea, "改用中文");
    await user.click(screen.getByRole("button", { name: "发送纠偏" }));
    expect(onSend).toHaveBeenCalledWith("改用中文");

    await user.click(screen.getByRole("button", { name: "停止生成" }));
    expect(onStop).toHaveBeenCalledTimes(1);
  });

  it("shows a single button while busy: stop when empty, send once text is typed", async () => {
    render(<Composer onSend={() => {}} disabled onStop={() => {}} />);
    const user = userEvent.setup();

    // 空输入时只有一个"停止生成"按钮，没有重复的发送按钮。
    expect(screen.getByRole("button", { name: "停止生成" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "发送纠偏" })).not.toBeInTheDocument();

    // 一旦输入内容，按钮切换成"发送纠偏"，停止按钮消失（同一个按钮槽位，不是两个按钮并存）。
    await user.type(screen.getByLabelText("输入消息"), "改用中文");
    expect(screen.getByRole("button", { name: "发送纠偏" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "停止生成" })).not.toBeInTheDocument();
  });

  it("stays disabled while busy without an onStop (e.g. creating a task)", () => {
    render(<Composer onSend={() => {}} disabled />);
    expect(screen.getByLabelText("输入消息")).toBeDisabled();
  });

  it("shows the bound agent tag and removes it on demand", async () => {
    const onSelectAgent = vi.fn();
    render(
      <Composer
        onSend={() => {}}
        disabled={false}
        agent={{ id: "a1", name: "周报助手" }}
        agents={[{ id: "a1", name: "周报助手" }]}
        onSelectAgent={onSelectAgent}
      />,
    );
    const user = userEvent.setup();

    expect(screen.getByText("@周报助手")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "移除智能体 周报助手" }));
    expect(onSelectAgent).toHaveBeenCalledWith(null);
  });

  it("opens the picker on @, binds the picked agent and strips the @query", async () => {
    const onSelectAgent = vi.fn();

    function Harness() {
      const [draft, setDraft] = useState("");
      return (
        <Composer
          onSend={() => {}}
          disabled={false}
          value={draft}
          onChange={setDraft}
          agents={[
            { id: "a1", name: "周报助手" },
            { id: "a2", name: "代码审查员" },
          ]}
          onSelectAgent={onSelectAgent}
        />
      );
    }

    render(<Harness />);
    const user = userEvent.setup();

    await user.type(screen.getByLabelText("输入消息"), "@周");
    await user.click(await screen.findByRole("option", { name: "@周报助手" }));

    expect(onSelectAgent).toHaveBeenCalledWith({ id: "a1", name: "周报助手" });
    expect(screen.getByLabelText("输入消息")).toHaveValue("");
  });

  it("does not render an @ trigger by default", () => {
    render(
      <Composer
        onSend={() => {}}
        disabled={false}
        agents={[{ id: "a1", name: "周报助手" }]}
        onSelectAgent={() => {}}
      />,
    );
    expect(screen.queryByRole("button", { name: "选择智能体" })).not.toBeInTheDocument();
    expect(screen.queryByText("@")).not.toBeInTheDocument();
  });

  it("does not open the picker while busy so the binding cannot change mid-run", async () => {
    render(
      <Composer
        onSend={() => {}}
        disabled
        onStop={() => {}}
        agents={[{ id: "a1", name: "周报助手" }]}
        onSelectAgent={() => {}}
      />,
    );
    const user = userEvent.setup();

    await user.type(screen.getByLabelText("输入消息"), "@");
    expect(screen.queryByRole("option")).not.toBeInTheDocument();
  });
});

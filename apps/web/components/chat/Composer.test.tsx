// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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
});

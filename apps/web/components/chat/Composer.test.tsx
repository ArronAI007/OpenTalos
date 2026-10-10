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

  it("stays disabled while busy without an onStop (e.g. creating a task)", () => {
    render(<Composer onSend={() => {}} disabled />);
    expect(screen.getByLabelText("输入消息")).toBeDisabled();
  });
});

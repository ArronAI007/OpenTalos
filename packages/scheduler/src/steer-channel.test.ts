import { describe, expect, it } from "vitest";
import { SteerChannelImpl } from "./steer-channel.js";

describe("SteerChannelImpl", () => {
  it("resolves waitForNext() when deliver() is called afterward", async () => {
    const channel = new SteerChannelImpl();
    const promise = channel.waitForNext();
    channel.deliver("turn left instead");
    await expect(promise).resolves.toBe("turn left instead");
  });

  it("buffers a delivered message when there is no active waiter yet, so the NEXT waitForNext() call resolves immediately", async () => {
    // Regression coverage: a node's generator is genuinely suspended (not executing any await)
    // for the entire window between yielding awaiting_tool and being resumed with the tool result
    // (see GraphEngine.runNodeToCompletion) -- a steer delivered during exactly that window, with
    // nothing actively racing it, must not be silently lost.
    const channel = new SteerChannelImpl();
    channel.deliver("turn left instead");
    await expect(channel.waitForNext()).resolves.toBe("turn left instead");
  });

  it("only buffers the latest message when deliver() is called twice with no waiter in between", async () => {
    const channel = new SteerChannelImpl();
    channel.deliver("first");
    channel.deliver("second");
    await expect(channel.waitForNext()).resolves.toBe("second");
  });

  it("each waitForNext() call only resolves once, requiring a fresh call for the next message", async () => {
    const channel = new SteerChannelImpl();
    channel.deliver("first");
    await expect(channel.waitForNext()).resolves.toBe("first");

    const second = channel.waitForNext();
    channel.deliver("second");
    await expect(second).resolves.toBe("second");
  });
});

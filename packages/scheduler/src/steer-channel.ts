import type { SteerChannel } from "@opentalos/core-graph";

/** Concrete SteerChannel used by Worker: one instance per task attempt, created alongside the
 * attempt's own AbortController (see worker.ts's runWithTimeout). Buffers a delivered message when
 * there's no active waiter yet, rather than discarding it -- a node's generator is genuinely
 * suspended (executing no await) for the whole window between yielding awaiting_tool and being
 * resumed with the tool result, so a steer arriving in exactly that window must not be lost; it's
 * picked up by the next waitForNext() call instead (see the design spec's non-goal: a steer that
 * arrives mid-tool-execution is applied at the start of the next round, with no special-casing
 * needed as a direct result of this buffering).
 *
 * Supports only ONE in-flight waitForNext() call at a time, matching how it's actually used (a
 * single node awaiting the next steer). A second waitForNext() call before the first has resolved
 * overwrites `resolver`, so the first caller's promise never resolves — there is no fan-out to
 * multiple concurrent waiters. */
export class SteerChannelImpl implements SteerChannel {
  private pendingMessage: string | undefined;
  private resolver: ((message: string) => void) | undefined;

  waitForNext(): Promise<string> {
    if (this.pendingMessage !== undefined) {
      const message = this.pendingMessage;
      this.pendingMessage = undefined;
      return Promise.resolve(message);
    }
    return new Promise((resolve) => {
      this.resolver = resolve;
    });
  }

  deliver(message: string): void {
    if (this.resolver) {
      const resolve = this.resolver;
      this.resolver = undefined;
      resolve(message);
    } else {
      this.pendingMessage = message;
    }
  }
}

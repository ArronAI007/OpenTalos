import { beforeEach, describe, expect, it } from "vitest";
import { stashHomeDraft, takeHomeDraft } from "./pending-message";

describe("stashHomeDraft / takeHomeDraft", () => {
  beforeEach(() => {
    sessionStorage.clear();
  });

  it("returns the stashed content once, then null", () => {
    stashHomeDraft("帮我查一下今天是几号");

    expect(takeHomeDraft()).toBe("帮我查一下今天是几号");
    expect(takeHomeDraft()).toBeNull();
  });

  it("returns null when nothing was stashed", () => {
    expect(takeHomeDraft()).toBeNull();
  });
});

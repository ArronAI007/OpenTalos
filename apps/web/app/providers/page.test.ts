import { describe, expect, test } from "vitest";
import { applyChatPreset } from "./page";

describe("applyChatPreset", () => {
  test("anthropic preset has no default base url", () => {
    expect(applyChatPreset({ key: "anthropic", label: "Anthropic", backend: "anthropic" })).toEqual({
      backend: "anthropic",
      baseUrl: "",
    });
  });

  test("openai-compatible preset carries its default base url", () => {
    expect(
      applyChatPreset({
        key: "openai",
        label: "OpenAI",
        backend: "openai-compatible",
        baseUrl: "https://api.openai.com/v1",
      })
    ).toEqual({ backend: "openai-compatible", baseUrl: "https://api.openai.com/v1" });
  });
});

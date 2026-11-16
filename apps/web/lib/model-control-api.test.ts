import { describe, expect, test } from "vitest";
import {
  modelControlModelsUrl,
  modelControlPresetDefaults,
  parseRoutingTargets,
  parseWeightedRoutingTargets,
} from "./model-control-api";

describe("modelControlPresetDefaults", () => {
  test("keeps custom compatible providers blank", () => {
    expect(
      modelControlPresetDefaults({
        id: "openai-compatible",
        label: "OpenAI-compatible",
        backend: "openai-compatible",
        default_base_url: null,
        api_key_label: "API key",
        supports_model_discovery: true,
      })
    ).toEqual({ backend: "openai-compatible", baseUrl: "" });
  });

  test("applies a provider default base url", () => {
    expect(
      modelControlPresetDefaults({
        id: "deepseek",
        label: "DeepSeek",
        backend: "openai-compatible",
        default_base_url: "https://api.deepseek.com",
        api_key_label: "API key",
        supports_model_discovery: true,
      })
    ).toEqual({
      backend: "openai-compatible",
      baseUrl: "https://api.deepseek.com",
    });
  });
});

describe("modelControlModelsUrl", () => {
  test("encodes account and search filters", () => {
    expect(modelControlModelsUrl("http://localhost:8400", "account 1", "gpt 4")).toBe(
      "http://localhost:8400/api/model-control/models?account_id=account+1&q=gpt+4"
    );
  });
});

describe("parseRoutingTargets", () => {
  test("parses comma and newline separated routing targets", () => {
    expect(parseRoutingTargets("openai/gpt-4o, group/backup\nanthropic/claude")).toEqual([
      { target: "openai/gpt-4o", weight: 1 },
      { target: "group/backup", weight: 1 },
      { target: "anthropic/claude", weight: 1 },
    ]);
  });

  test("parses explicit routing weights", () => {
    expect(
      parseWeightedRoutingTargets("openai/gpt-5 | 3, group/backup @ 2")
    ).toEqual([
      { target: "openai/gpt-5", weight: 3 },
      { target: "group/backup", weight: 2 },
    ]);
  });
});

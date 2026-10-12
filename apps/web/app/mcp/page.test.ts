import { describe, expect, test } from "vitest";
import { parseEnvLines } from "./page";

describe("parseEnvLines", () => {
  test("parses multiple KEY=VALUE lines", () => {
    expect(parseEnvLines("FOO=bar\nBAZ=qux")).toEqual({ FOO: "bar", BAZ: "qux" });
  });

  test("trims whitespace around lines", () => {
    expect(parseEnvLines("  FOO=bar  \n  BAZ=qux  ")).toEqual({ FOO: "bar", BAZ: "qux" });
  });

  test("ignores blank lines", () => {
    expect(parseEnvLines("FOO=bar\n\n\nBAZ=qux")).toEqual({ FOO: "bar", BAZ: "qux" });
  });

  test("ignores lines without an equals sign", () => {
    expect(parseEnvLines("FOO=bar\nNOT_VALID_LINE")).toEqual({ FOO: "bar" });
  });

  test("keeps everything after the first equals sign as the value", () => {
    expect(parseEnvLines("FOO=bar=baz")).toEqual({ FOO: "bar=baz" });
  });

  test("returns undefined for an empty string", () => {
    expect(parseEnvLines("")).toBeUndefined();
  });

  test("returns undefined when every line is malformed", () => {
    expect(parseEnvLines("not valid\nalso not valid")).toBeUndefined();
  });
});

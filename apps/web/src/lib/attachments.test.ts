import { describe, expect, it } from "vitest";
import { formatTextAttachment, isImageFile, isTextFile } from "./attachments.js";

describe("isImageFile", () => {
  it("returns true for a file with an image/* MIME type", () => {
    expect(isImageFile(new File([""], "cat.png", { type: "image/png" }))).toBe(true);
  });

  it("returns false for a non-image MIME type", () => {
    expect(isImageFile(new File([""], "notes.txt", { type: "text/plain" }))).toBe(false);
  });
});

describe("isTextFile", () => {
  it("returns true for a text/* MIME type", () => {
    expect(isTextFile(new File([""], "notes.txt", { type: "text/plain" }))).toBe(true);
  });

  it("returns true for a known code extension even with an empty/generic MIME type", () => {
    expect(isTextFile(new File([""], "script.py", { type: "" }))).toBe(true);
    expect(isTextFile(new File([""], "component.tsx", { type: "application/octet-stream" }))).toBe(true);
  });

  it("returns false for an image file", () => {
    expect(isTextFile(new File([""], "cat.png", { type: "image/png" }))).toBe(false);
  });

  it("returns false for an unrecognized binary extension", () => {
    expect(isTextFile(new File([""], "archive.zip", { type: "application/zip" }))).toBe(false);
  });
});

describe("formatTextAttachment", () => {
  it("wraps the content in a fenced code block labeled with the filename", () => {
    expect(formatTextAttachment("script.py", "print(1)")).toBe('\n\n[附件: script.py]\n```\nprint(1)\n```');
  });
});

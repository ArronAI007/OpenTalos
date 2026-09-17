/** Matches apps/api's MAX_IMAGES_PER_MESSAGE. */
export const MAX_IMAGES_PER_MESSAGE = 4;

/** Cap on the RAW file, before base64 encoding — base64 inflates size by ~4/3, so this keeps the
 * resulting data URI comfortably under apps/api's MAX_IMAGE_DATA_URI_BYTES (6MB). */
export const MAX_IMAGE_FILE_BYTES = 4.5 * 1024 * 1024;

/** Text files are read in full and inlined into the outgoing message text (see
 * formatTextAttachment) — kept much smaller than an image cap so a single attachment can't
 * dominate apps/api's overall MAX_MESSAGE_LENGTH on its own. */
export const MAX_TEXT_FILE_BYTES = 200 * 1024;

const TEXT_FILE_EXTENSIONS = [
  ".txt",
  ".md",
  ".py",
  ".js",
  ".jsx",
  ".ts",
  ".tsx",
  ".json",
  ".csv",
  ".yaml",
  ".yml",
  ".html",
  ".css",
  ".sh",
  ".sql",
  ".java",
  ".go",
  ".rs",
  ".c",
  ".cpp",
  ".h",
  ".rb",
  ".php",
];

export interface PendingAttachment {
  id: string;
  name: string;
  size: number;
  kind: "image" | "text";
  /** "loading" from the moment a file is accepted (passed type/count/size checks) until its
   * FileReader read resolves — shown as a spinner chip in the composer so a large image doesn't
   * appear to silently do nothing while it's being base64-encoded. Never sent while "loading": the
   * composer's submit() blocks sending until every attachment reaches "ready" (dataUrl/textContent
   * only exist once it does). */
  status: "loading" | "ready";
  /** Set when kind === "image" — a "data:image/...;base64,..." URI, sent as-is to the backend. */
  dataUrl?: string;
  /** Set when kind === "text" — the file's raw text content, inlined into the message on send. */
  textContent?: string;
}

export function isImageFile(file: File): boolean {
  return file.type.startsWith("image/");
}

export function isTextFile(file: File): boolean {
  if (file.type.startsWith("text/")) return true;
  const lowerName = file.name.toLowerCase();
  return TEXT_FILE_EXTENSIONS.some((ext) => lowerName.endsWith(ext));
}

export function readFileAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result as string);
    reader.onerror = () => reject(reader.error ?? new Error(`Failed to read "${file.name}"`));
    reader.readAsDataURL(file);
  });
}

export function readFileAsText(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result as string);
    reader.onerror = () => reject(reader.error ?? new Error(`Failed to read "${file.name}"`));
    reader.readAsText(file);
  });
}

/** Labels a text attachment's content by filename so both the model and a human re-reading the
 * sent message later can tell where the block came from. */
export function formatTextAttachment(name: string, content: string): string {
  return `\n\n[附件: ${name}]\n\`\`\`\n${content}\n\`\`\``;
}

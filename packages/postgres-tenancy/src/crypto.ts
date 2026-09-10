import { createHash, randomBytes, randomUUID } from "node:crypto";

const KEY_PREFIX_TAG = "tk_";
const KEY_RANDOM_BYTES = 32;
/** 展示识别用的截取长度：完整覆盖 `KEY_PREFIX_TAG` 加上几位十六进制随机字符，足够在管理页面
 * 列表里区分不同的 key，但远不足以被用来重建完整密钥。 */
const DISPLAY_PREFIX_LENGTH = 12;

export interface GeneratedApiKey {
  id: string;
  rawKey: string;
  keyPrefix: string;
  keyHash: string;
}

/** API Key 本身就是高熵随机值（不是用户挑选的低熵密码），一次性哈希（SHA-256）而不是
 * bcrypt/argon2 这类为低熵密码设计的慢哈希就足够安全，且不需要额外依赖。 */
export function generateApiKey(): GeneratedApiKey {
  const id = randomUUID();
  const rawKey = `${KEY_PREFIX_TAG}${randomBytes(KEY_RANDOM_BYTES).toString("hex")}`;
  return { id, rawKey, keyPrefix: rawKey.slice(0, DISPLAY_PREFIX_LENGTH), keyHash: hashApiKey(rawKey) };
}

export function hashApiKey(rawKey: string): string {
  return createHash("sha256").update(rawKey).digest("hex");
}

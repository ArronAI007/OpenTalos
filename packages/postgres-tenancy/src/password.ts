import bcrypt from "bcrypt";

// 12 是 bcrypt 目前的常见安全默认值（cost factor），在普通服务器上单次哈希约 200-300ms，
// 足够慢到抵抗离线暴力破解，又不至于让注册/登录请求变得难以忍受。
const SALT_ROUNDS = 12;

export async function hashPassword(password: string): Promise<string> {
  return bcrypt.hash(password, SALT_ROUNDS);
}

export async function verifyPassword(password: string, hash: string): Promise<boolean> {
  return bcrypt.compare(password, hash);
}

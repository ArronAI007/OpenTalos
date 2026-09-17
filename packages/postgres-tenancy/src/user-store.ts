import { eq, sql } from "drizzle-orm";
import { drizzle, type NodePgDatabase } from "drizzle-orm/node-postgres";
import type { Pool } from "pg";
import { users } from "./schema.js";
import type { TenantStore } from "./store.js";
import { hashPassword, verifyPassword } from "./password.js";

export interface UserRecord {
  id: string;
  tenantId: string;
  username: string;
  status: "active" | "banned" | "deleted";
  createdAt: string;
  updatedAt: string;
}

export type RegisterResult =
  | { outcome: "created"; user: UserRecord; rawApiKey: string }
  | { outcome: "username_taken" };

export type LoginResult =
  | { outcome: "success"; rawApiKey: string }
  | { outcome: "invalid_credentials" }
  | { outcome: "account_blocked" };

type UserRow = typeof users.$inferSelect;

const POSTGRES_UNIQUE_VIOLATION = "23505";

function hasUniqueViolationCode(error: unknown): boolean {
  return typeof error === "object" && error !== null && "code" in error && (error as { code?: unknown }).code === POSTGRES_UNIQUE_VIOLATION;
}

/** drizzle-orm 把底层 pg 驱动抛出的错误包在 `DrizzleQueryError` 里，真正带 `code: "23505"` 的
 * pg 错误对象在 `.cause` 上，而不是顶层——所以要顺着 `.cause` 链查找，不能只看顶层 error。 */
function isUniqueViolation(error: unknown): boolean {
  let current: unknown = error;
  while (current) {
    if (hasUniqueViolationCode(current)) return true;
    current = current instanceof Error ? current.cause : undefined;
  }
  return false;
}

export class UserStore {
  private readonly db: NodePgDatabase;

  constructor(
    pool: Pool,
    private readonly tenantStore: TenantStore,
  ) {
    this.db = drizzle(pool);
  }

  /** 先创建 tenant + api_key，再插入 users 行——不是单个跨表 SQL 事务（TenantStore 的方法各自
   * 绑定同一个 Pool，没有暴露"传入外部事务"的接口，见本文件所在 plan 开头的说明）。
   * `users.username` 的唯一索引才是"是否重复"的权威判断：插入时捕获唯一约束冲突，
   * 说明存在并发重复注册，把刚创建的 tenant 禁用（补偿操作）后返回 username_taken。 */
  async register(username: string, password: string): Promise<RegisterResult> {
    const normalized = username.trim();
    const passwordHash = await hashPassword(password);

    const tenant = await this.tenantStore.createTenant(`user:${normalized}`);
    const { rawKey } = await this.tenantStore.createApiKey(tenant.id);

    const id = crypto.randomUUID();
    try {
      const [row] = await this.db
        .insert(users)
        .values({ id, tenantId: tenant.id, username: normalized, passwordHash, status: "active" })
        .returning();
      return { outcome: "created", user: this.toUserRecord(row), rawApiKey: rawKey };
    } catch (error) {
      if (isUniqueViolation(error)) {
        await this.tenantStore.setTenantStatus(tenant.id, "disabled");
        return { outcome: "username_taken" };
      }
      throw error;
    }
  }

  /** 每次成功登录都会签发一个全新的 API Key，而不是尝试找回之前的——api_keys.key_hash 只存哈希，
   * 原始 key 从创建那一刻起就不可逆，无法在后续登录时"复用"。一个 tenant 同时存在多个 active
   * key 与 apps/admin 的 ApiKeyPanel 本身允许的情况一致，不是新的不一致。 */
  async login(username: string, password: string): Promise<LoginResult> {
    const row = await this.findRowByUsername(username);
    if (!row) return { outcome: "invalid_credentials" };

    const passwordMatches = await verifyPassword(password, row.passwordHash);
    if (!passwordMatches) return { outcome: "invalid_credentials" };

    if (row.status !== "active") return { outcome: "account_blocked" };

    const tenant = await this.tenantStore.getTenant(row.tenantId);
    if (!tenant || tenant.status !== "active") return { outcome: "account_blocked" };

    const { rawKey } = await this.tenantStore.createApiKey(row.tenantId);
    return { outcome: "success", rawApiKey: rawKey };
  }

  async listUsers(): Promise<UserRecord[]> {
    const rows = await this.db.select().from(users);
    return rows.map((row) => this.toUserRecord(row));
  }

  async getUser(id: string): Promise<UserRecord | undefined> {
    const rows = await this.db.select().from(users).where(eq(users.id, id)).limit(1);
    return rows[0] ? this.toUserRecord(rows[0]) : undefined;
  }

  async setUserStatus(id: string, status: "active" | "banned" | "deleted"): Promise<void> {
    await this.db.update(users).set({ status, updatedAt: new Date() }).where(eq(users.id, id));
  }

  private async findRowByUsername(username: string): Promise<UserRow | undefined> {
    const rows = await this.db
      .select()
      .from(users)
      .where(sql`lower(${users.username}) = lower(${username.trim()})`)
      .limit(1);
    return rows[0];
  }

  private toUserRecord(row: UserRow): UserRecord {
    return {
      id: row.id,
      tenantId: row.tenantId,
      username: row.username,
      status: row.status as "active" | "banned" | "deleted",
      createdAt: row.createdAt.toISOString(),
      updatedAt: row.updatedAt.toISOString(),
    };
  }
}

import type { FastifyInstance } from "fastify";
import type { UserStore } from "@opentalos/postgres-tenancy";

export interface AuthRouteDeps {
  userStore: UserStore;
}

const MIN_USERNAME_LENGTH = 3;
const MAX_USERNAME_LENGTH = 32;
const MIN_PASSWORD_LENGTH = 8;

interface RegisterBody {
  username?: string;
  password?: string;
}

interface LoginBody {
  username?: string;
  password?: string;
}

/** 公开路由，不挂任何鉴权 preHandler（见 server.ts 里这个 scope 的注册方式）——注册/登录本身
 * 就是获得凭证的入口，不能要求先持有凭证。 */
export function registerAuthRoutes(app: FastifyInstance, deps: AuthRouteDeps): void {
  const { userStore } = deps;

  app.post<{ Body: RegisterBody }>("/auth/register", async (request, reply) => {
    const username = request.body?.username?.trim();
    if (!username || username.length < MIN_USERNAME_LENGTH || username.length > MAX_USERNAME_LENGTH) {
      return reply.code(400).send({ error: `用户名长度需在 ${MIN_USERNAME_LENGTH}-${MAX_USERNAME_LENGTH} 位之间` });
    }
    const password = request.body?.password;
    if (!password || password.length < MIN_PASSWORD_LENGTH) {
      return reply.code(400).send({ error: `密码至少需要 ${MIN_PASSWORD_LENGTH} 位` });
    }

    const result = await userStore.register(username, password);
    if (result.outcome === "username_taken") {
      return reply.code(409).send({ error: "用户名已被占用" });
    }
    return reply.code(201).send({ apiKey: result.rawApiKey });
  });

  app.post<{ Body: LoginBody }>("/auth/login", async (request, reply) => {
    const username = request.body?.username?.trim();
    const password = request.body?.password;
    if (!username || !password) {
      return reply.code(400).send({ error: "用户名和密码不能为空" });
    }

    const result = await userStore.login(username, password);
    if (result.outcome === "invalid_credentials") {
      return reply.code(401).send({ error: "用户名或密码错误" });
    }
    if (result.outcome === "account_blocked") {
      return reply.code(403).send({ error: "账号已被封禁" });
    }
    return reply.send({ apiKey: result.rawApiKey });
  });
}

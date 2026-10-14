# Contract: OAuth 客户端子集

对应 User Story 5、FR-011/FR-012、SC-007。**安全敏感**——实现/评审时按宪法"安全敏感代码需要额
外谨慎"的要求，先过一轮专门的安全检查（凭据存储、PKCE 校验、重定向 URL 处理）再合并。

## 公共入口

```python
class AuthProvider(Protocol):
    async def token(self) -> str | None: ...
    async def on_unauthorized(self, context: dict[str, Any] | None = None) -> None: ...

class OAuthStateStore(Protocol):
    async def load(self, server_url: str) -> MCPOAuthState | None: ...
    async def save(self, server_url: str, state: MCPOAuthState) -> None: ...

class MCPOAuthProvider:
    def __init__(self, server_url: str, store: OAuthStateStore, *, client_metadata: dict[str, Any]) -> None: ...
    async def start_authorization(self) -> str:  # 返回授权 URL
        ...
    async def complete_authorization(self, authorization_code: str, state_param: str) -> None: ...
```

## 行为契约

1. **未授权时的明确信号**（FR-011 Acceptance Scenario 1）：第一次连接一个要求 OAuth 的服务器且
   本地没有可用凭据时，必须抛出 `MCPOAuthAuthorizationRequiredError`（携带授权 URL），不能表现
   成普通的 `MCPConnectionError`/连接超时——调用方需要能区分"该发起授权流程了"和"单纯连不上"。
2. **PKCE 授权码流程 + state 的 CSRF 校验**：`start_authorization()` 生成 `code_verifier` + 一个
   随机 `state`（都存入注入的 `OAuthStateStore`）+ 对应的 S256 `code_challenge`，构造授权 URL；
   `complete_authorization(code, state_param)` 要求调用方把授权服务器原样回传的 `state` 查询参
   数传回来，和存下的值用常数时间比较（`secrets.compare_digest`）核对一致才继续——不一致直接拒
   绝（防止攻击者诱导受害者带着攻击者自己的授权码完成流程）；核对通过后用存下的 `code_verifier`
   换 token，成功后把 `OAuthTokens` 存回 `store`，并清空这次的 `state`/`code_verifier`（一次性，
   不能重放）。
3. **动态客户端注册**：授权服务器元数据里有 `registration_endpoint` 且本地没有已注册的
   `client_information` 时自动注册一次，注册结果存入 `store`。
4. **token 刷新 + 并发 401 去重**（FR-011、User Story 5 Acceptance Scenario 3）：收到 401 时用
   `refresh_token` 换新 `access_token` 并对原请求重试一次，调用方无感知；同一时刻多个请求各自
   收到 401 时，只能触发一次真正的刷新请求，其余请求必须等待并复用这同一次刷新的结果（不能各
   自发起一次刷新请求）——用一个模块/实例作用域的"进行中刷新"`asyncio.Future` 实现（第二个及
   以后的 401 处理者检测到已有进行中的刷新时直接 `await` 同一个 Future，不新建请求）。
5. **step-up 授权**（FR-011、Acceptance Scenario 4）：某次操作收到 `insufficient_scope` 错误
   时，触发一次申请"已授予 scope ∪ 服务端要求的 scope"的新授权流程，而不是把这个错误原样抛给
   调用方。
6. **未配置 OAuth 的服务器不受影响**（FR-011 收尾半句）：`MCPServerConfig` 没有配置
   `auth_provider`（没有标注需要 OAuth）的连接路径完全不执行任何发现/token 相关代码，不能因为
   "系统里存在 OAuth 支持代码"就强制所有连接都先走一遍发现流程。
7. **凭据存储可注入**（FR-012）：`OAuthStateStore` 是一个 `typing.Protocol`，`packages/mcpclient`
   只提供一个 `MemoryOAuthStateStore`（供测试/默认行为），真正持久化到哪（文件/SQLite/密钥管
   理服务）完全由调用方决定，这个包不做选择也不做假设。
8. **回调接收**（见 research.md Decision 6、`oauth/callback.py` 的 `PendingCallbackRegistry`）：
   `register(state)` 和真正接收 HTTP 回调请求的路由（`apps/api/main.py` 新增）是分离的——这个
   包本身不监听任何端口。
9. **元数据结构校验安全检查**：发现响应里的任意 URL 字段必须拒绝 `javascript:`/`data:`/
   `vbscript:` scheme；`issuer` 字段必须和请求的服务器 URL 匹配（除非显式传入
   `skip_issuer_validation`，默认不跳过）。

## 独立测试方式

- 用假的授权服务器端点（测试里手写的、返回固定发现元数据/token 响应的 handler）跑一次完整的
  PKCE 授权码换 token 流程，断言最终 `OAuthTokens` 被存入注入的 `store`。
- 并发测试：模拟 5 个请求同时收到 401，断言底层只发出一次真正的刷新 HTTP 请求（用一个计数器
  mock token 端点）。
- 安全测试：构造一个 `issuer` 字段不匹配的发现响应，断言 `discover_authorization_server_metadata`
  抛 `OAuthIssuerMismatchError`；构造一个 `authorization_endpoint="javascript:alert(1)"` 的元数
  据，断言被拒绝。

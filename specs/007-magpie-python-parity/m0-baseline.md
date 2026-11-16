# M0 基线：Magpie 桌面端 Python 功能对等

**状态**: Complete

**开始日期**: 2026-11-16

**目标**: 把“完整实现 Magpie 桌面端所有功能”转换成不可漂移、可机器校验、可逐项验收的工程基线。

## 上游锁定

- Repository: `https://github.com/yetone/magpie`
- Pinned commit: `9dcec6751323674bc1ad9f52b13ec8fc081b4de6`
- License: MIT
- 锁定方式: commit SHA，不使用会移动的 `main` 或“最新版”
- 权威功能来源:
  - `README.md`
  - `README.md#supported-agents`
  - `README.md#how-it-fits-together`
  - `README.md#what-it-does`
  - 当前提交内的 Go 源码、桌面资源与构建文件

`main` 后续新增的功能不会自动扩大本项目范围。需要升级基线时，必须新建一份 manifest，记录新 commit、
能力差异、迁移影响和回归结果。

## OpenTalos 当前基线

- Commit: `70a3d6f1ca542e29858c7974183bcc3ed05f357a`
- Python: `>=3.12`
- 后端: FastAPI、Uvicorn、SQLite
- Agent: OpenTalos ReAct runtime
- 前端: Next.js 16、React 19、TypeScript
- 已有可复用能力: Provider 配置、模型调用、SSE、Skills、MCP、Web Search、Memory、Observability

## M0 交付物

| 文件 | 用途 |
|---|---|
| `capability-manifest.json` | 130 项用户可见能力、状态、优先级、里程碑、验收标准与来源 |
| `capability-manifest.schema.json` | manifest 的机器可读结构约束 |
| `agent-catalog.json` | 固定基线 README 中列出的 87 个 Agent |
| `scripts/check_magpie_parity.py` | 校验 commit、能力唯一性、工作面覆盖和 Agent 目录 |
| `tests/test_magpie_parity_baseline.py` | 保证基线不会在无审查时被破坏 |
| `m0-baseline.md` | 本文件，定义范围、质量门禁和变更规则 |

## 对等定义

“完全实现”按以下维度验收，不要求复制 Go 源码结构：

1. 用户可见工作流一致。
2. Gateway 协议行为与流式语义一致。
3. 支持的 Agent 目录全部有适配器或明确兼容路径。
4. macOS、Windows、Linux 桌面能力与发布路径一致。
5. 多 Provider、多账号、配额、路由、脱敏、插件、统计和共享能力可独立验收。
6. OpenTalos 原有功能不退化。

## 状态规则

- `implemented`: 已通过该能力全部验收测试，并且不再依赖临时兼容分支。
- `partial`: OpenTalos 已存在部分基础，但未达到 Magpie 基线完整行为。
- `gap`: 当前没有可验收实现。
- manifest 中不允许使用“差不多完成”“基本可用”等模糊状态。

## 工作面

| Area | 能力数 | 说明 |
|---|---:|---|
| `control_plane` | 8 | Provider、模型、导入、Profile、代理 |
| `accounts` | 11 | 订阅、多账号、预热、导入导出 |
| `gateway` | 12 | 四种协议、流式、工具、reasoning、middleware |
| `routing` | 12 | 路由组、模式、粘性、意图路由、约束 |
| `agents` | 9 | 87 Agent 目录、配置事务、Library、WSL |
| `usage` | 12 | Token、成本、配额、会话、OTLP |
| `privacy` | 7 | 脱敏、PII、占位符、审计、fail-closed |
| `tools` | 12 | Search、MCP、图片视频、Memory、插件 |
| `desktop` | 18 | 菜单栏、面板、窗口、快捷键、CLI/TUI、Linux |
| `sharing` | 10 | LAN、Gateway Key、mTLS、Remote、Docker |
| `operations` | 11 | 备份、同步、服务、诊断、网络、崩溃恢复 |
| `release` | 8 | 三平台打包、签名、更新、许可证、迁移 |

## 验收命令

```bash
.venv/bin/python scripts/check_magpie_parity.py
.venv/bin/python -m pytest -p no:capture tests/test_magpie_parity_baseline.py -q
```

本机 Python 的 `readline` 扩展会触发段错误，因此常规 pytest 必须显式使用
`-p no:capture`。该限制属于运行环境问题，不是 OpenTalos 业务逻辑失败。

## 冻结的测试结果

后端确定性回归使用 mock 模型并清空外部服务密钥，避免把真实模型、供应商可用性和付费调用混入基线：

```bash
MODEL_PROVIDER=mock MODEL_NAME=mock-model MODEL_API_KEY='' TAVILY_API_KEY='' \
  .venv/bin/python -m pytest -p no:capture tests/ -q
```

结果: `835 passed, 7 skipped in 170.70s`。依赖本地套接字的 A2A/MCP 测试通过；7 个跳过项是需要真实
模型或外部服务的自测。

前端结果:

- Vitest: `21` 个测试文件、`173 passed`
- ESLint: 无错误
- 基线修正: 将 4 处 JSX 文本中的半角双引号改为中文引号，行为不变

Magpie parity 基线结果:

- `130` 项能力
- `87` 个受支持 Agent
- `17` 项 `partial`
- `113` 项 `gap`
- `5 passed` manifest/contract 测试

当前机器上的 `pnpm` 版本签名在离线环境中无法验证，因此前端测试和 lint 直接调用
`apps/web/node_modules/.bin/` 中已安装的 `vitest` 与 `eslint`。

## 变更规则

1. 新能力先修改 manifest 和测试，再写实现。
2. 任何能力从 `gap`/`partial` 变为 `implemented`，必须附对应自动化测试路径和平台验证记录。
3. 不能通过删除能力、扩大“兼容路径”定义或降低验收标准来达成完成率。
4. 上游功能升级必须产生新的 baseline id、commit、差异报告和影响评估。
5. 每个里程碑都要运行 OpenTalos 全量回归，确认现有聊天、SSE、Skills、MCP、Memory、
   DeepResearch、AgentRL 和 A2A 不退化。

## M0 完成条件

- 上游 commit 已锁定。
- `capability-manifest.json` 覆盖十二个工作面。
- Agent 目录完整记录固定基线中的 87 个 Agent。
- 校验脚本和 pytest 基线测试通过。
- OpenTalos 后端、前端测试结果已记录。
- 后续实现只通过 manifest 状态和测试证据推进。

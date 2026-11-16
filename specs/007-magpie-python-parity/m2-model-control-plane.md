# M2 模型控制面（Slice 1）

**状态**: Core Complete

**日期**: 2026-11-16

## 已完成

- 独立 `model_platform` 包。
- 多 Provider Key 账号存储。
- 账号级 HTTP/SOCKS 代理字段。
- Provider 预设目录，覆盖当前主要 OpenAI/Anthropic-compatible 服务。
- OpenAI-compatible 与 Anthropic 模型发现。
- 发现模型写入本地模型目录。
- 本地模型能力合并：上下文窗口、工具、thinking。
- 旧 `provider_configs` 到新控制面的幂等导入。
- 控制面快照的保存、列表和删除。
- 新控制面 API。
- Provider 页面中的账号、模型刷新、代理和快照管理界面。

## 数据边界

旧 `provider_configs` 继续供现有聊天运行时使用，不删除、不改写。新控制面使用：

- `control_provider_accounts`
- `control_models`
- `control_profiles`

这些表与旧配置位于同一 SQLite 数据库，通过增量建表加入，不需要破坏性迁移。

## API

| Method | Path | 用途 |
|---|---|---|
| GET | `/api/model-control/presets` | Provider 预设 |
| GET | `/api/model-control/accounts` | 多账号列表 |
| POST | `/api/model-control/accounts` | 新建账号 |
| PATCH | `/api/model-control/accounts/{id}` | 修改或启停账号 |
| DELETE | `/api/model-control/accounts/{id}` | 删除账号及模型 |
| POST | `/api/model-control/accounts/{id}/discover` | 刷新模型 |
| GET | `/api/model-control/models` | 查询模型 |
| POST | `/api/model-control/imports/legacy` | 导入旧 Provider 配置 |
| GET/POST | `/api/model-control/profiles` | 控制面快照 |
| DELETE | `/api/model-control/profiles/{id}` | 删除快照 |

## 安全约束

- API 永远不返回明文 API Key，只返回掩码。
- Base URL 和代理 URL 只接受受支持的 HTTP(S)/SOCKS scheme。
- 模型发现禁用环境代理自动继承；账号显式代理才生效。
- 现有明文数据库存储兼容保留；OS Keychain 迁移仍是后续安全任务。

## 尚未完成

- Magpie 全部 Provider 预设和动态 models.dev 元数据。
- CC Switch、Claude Code、Codex、Alma 的完整扫描、预览和去重 UI。
- Add-to-Magpie 导入链接。
- 模型 API 协议、reasoning level、价格的手工编辑器。
- 控制面快照的恢复动作和 Agent binding 快照。
- 控制面账号已接入 Gateway/Router；这一步属于 M3-M5。

## 验证

```bash
.venv/bin/python -m pytest -p no:capture tests/model_platform -q
.venv/bin/python -m pytest -p no:capture tests/apps/api/test_model_control_routes.py -q
pnpm -C apps/web test
```

结果：

- 控制面与 API 定向测试：`14 passed`
- 完整后端确定性回归：`862 passed, 7 skipped`
- 前端 Vitest：`22` 个文件、`176 passed`
- ESLint、TypeScript 和 Next.js production build：通过
- 桌面 API + Next.js + WebView 烟测：通过，退出后端口正常释放

# Implementation Plan: 把 DeepResearch 抽取成独立服务

**Branch**: `006-extract-deepresearch-service` | **Date**: 2026-10-15 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/006-extract-deepresearch-service/spec.md`

**Note**: This template is filled in by the `/speckit-plan` command; its definition describes the execution workflow.

## Summary

把 DeepResearch（主题规划→并行搜索总结→合成带引用报告）从 `apps/api` 里整体抽取成仓库根目
录下一个独立目录 `deepresearch/`，镜像 `agentrl/` 的组织方式（自己的 `pyproject.toml`、自己
的虚拟环境、自己的 FastAPI 入口、自己的独立端口 `:8440`、自己的 SQLite 存储）。技术方案：新
目录通过 sys.path 注入（而非字面意义的 uv path dependency，见 research.md Decision 1）复用
`packages/ai`（模型调用）和 `packages/websearch`（网页搜索）已有代码，不重新实现一遍；路由
路径改为镜像 AgentRL 的扁平约定（`/runs` 而非 `/api/deepresearch/runs`）；历史数据不迁移。
`apps/api` 删除 `deepresearch.py`、相关路由、`deepresearch_runs` 表；`scripts/start.sh` 新增
一个镜像 `agentrl` 接入方式的服务块；`apps/web` 的 `deepresearch-api.ts` 改请求目标地址和路
径，`deepresearch` 页面补一个降级提示。

## Technical Context

**Language/Version**: Python 3.12+（独立 `deepresearch/pyproject.toml`，和 `agentrl/`/根项
目一致的 `requires-python = ">=3.12"`）

**Primary Dependencies**: FastAPI + uvicorn（HTTP 服务，镜像 agentrl/main.py 的组织方式）、
pydantic（请求/响应模型 + `packages/core/protocol.py`/`packages/websearch/models.py` 需
要）、anthropic + openai + python-dotenv（`packages/ai/model.py` 需要）、httpx
（`packages/websearch/client.py` 需要）——这些都是 `deepresearch/pyproject.toml` 自己声明
的依赖，不引用根 `pyproject.toml`

**Storage**: SQLite，独立文件 `deepresearch/.data/deepresearch.db`（不与 `apps/api` 的
`chat.db` 共用）

**Testing**: pytest + pytest-asyncio，独立于根项目运行（`deepresearch/pyproject.toml` 自己
的 `[dependency-groups].dev`，`testpaths = ["tests"]`，镜像 `agentrl/pyproject.toml`）

**Target Platform**: 本地开发环境（macOS/Linux），通过 `scripts/start.sh` 或手动 `uv run`
启动的常驻 FastAPI 进程，和 `agentrl`/`a2apeer` 同一量级的轻量服务（不像 AgentRL 那样有
torch 这类平台受限依赖）

**Project Type**: web-service（仓库根目录下的独立子项目，镜像 `agentrl/` 的既有先例）

**Performance Goals**: SC-002（健康检查 10 秒内变绿）、SC-003（端到端耗时波动不超过抽取前
的 20%）

**Constraints**: FR-002（不依赖仓库根 `pyproject.toml`、不依赖 `apps/api` 目录下的任何
Python 模块）、FR-003（API 行为与抽取前逐字一致，只有路由路径形状改变）

**Scale/Scope**: 单开发者本地工具级别的并发规模（和 `apps/api`/`agentrl` 现状一致，不是面向
多租户生产负载设计），不在本次范围内新增可观测性/限流/鉴权机制

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| 原则 | 评估 |
|------|------|
| I. TDD（不可协商） | 符合——tasks.md 将按"先写失败测试、再实现"组织每个 User Story；`research.py`/`store.py`/`main.py` 的新增代码都配套测试（迁移自现状 `test_deepresearch.py` + 新增路由测试） |
| II. 代码规范一致性 | 符合——新目录延续根项目的 Python 风格（PEP 8/ruff 隐式约定，无新增 lint 配置需求）；前端改动在既有 ESLint 范围内 |
| III. 输入必须校验 | 符合——`POST /runs` 的 `topic` 校验、`TAVILY_API_KEY` 缺失时的 503，都在契约里显式声明（见 contracts/deepresearch-api.md） |
| IV. 简洁至上，拒绝过度工程 | 符合——research.md Decision 1 明确否决了"给三个无关目录各补 pyproject.toml"这种会放大改动范围的方案，选择影响面最小的 sys.path 注入；不新增迁移脚本（Decision 8） |
| V. 接口文档完整性 | 符合——contracts/deepresearch-api.md 覆盖全部对外路由的请求/响应/错误码 |

无违规，Complexity Tracking 留空。

## Project Structure

### Documentation (this feature)

```text
specs/006-extract-deepresearch-service/
├── plan.md              # This file (/speckit-plan command output)
├── research.md          # Phase 0 output (/speckit-plan command)
├── data-model.md        # Phase 1 output (/speckit-plan command)
├── quickstart.md        # Phase 1 output (/speckit-plan command)
├── contracts/
│   └── deepresearch-api.md
└── tasks.md             # Phase 2 output (/speckit-tasks command - NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
deepresearch/                    # 新增，镜像 agentrl/ 的组织方式
├── pyproject.toml                # 独立依赖声明：fastapi/uvicorn/pydantic/anthropic/openai/python-dotenv/httpx
├── main.py                       # FastAPI app + 5 个扁平路由 + /health（镜像 agentrl/main.py）
├── store.py                       # DeepResearchStore（镜像 agentrl/store.py 的 RunStore）
├── research.py                    # 迁移自 apps/api/deepresearch.py（含 sys.path 注入，见 Decision 1）
└── tests/
    ├── __init__.py
    ├── test_research.py           # 迁移自 tests/apps/api/test_deepresearch.py
    └── test_routes.py             # 新增，镜像 agentrl/tests/test_routes.py 风格

apps/api/
├── main.py                        # 删除 deepresearch 相关路由 + import
├── db.py                          # 删除 deepresearch_runs 表定义 + 7 个 CRUD 方法
└── (deepresearch.py 整体删除)

tests/apps/api/
├── test_api_routes.py             # 删除 deepresearch 相关路由测试
├── test_db.py                     # 删除 deepresearch 相关测试
└── (test_deepresearch.py 整体删除，内容已迁移到 deepresearch/tests/test_research.py)

scripts/start.sh                   # 新增一个镜像 agentrl 接入方式的 deepresearch 服务块

apps/web/
├── lib/deepresearch-api.ts        # 新增 DEEPRESEARCH_URL，5 个函数改 base URL + 路径
└── app/deepresearch/page.tsx      # 补一个 loadError 状态 + "服务未启动"提示（镜像 agentrl 页面）
```

**Structure Decision**：选择"仓库根目录下的独立子项目"这一结构（对应 plan 模板里未列出的
第四种选项——本仓库已有 `agentrl/` 作为先例，不是模板默认的 single-project/web-app/mobile
三选项之一）。`deepresearch/` 和 `agentrl/` 对等：都在仓库根目录、都有自己的
`pyproject.toml`、都通过 `scripts/start.sh` 统一管理，但都不属于根 `pyproject.toml` 声明的
工作区、也不属于 `apps/`（Web 应用）或 `packages/`（给 `apps/*` 复用的库）这两类现有目录。

## Complexity Tracking

无违规需要记录。

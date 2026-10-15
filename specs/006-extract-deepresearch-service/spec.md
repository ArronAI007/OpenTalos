# Feature Specification: 把 DeepResearch 抽取成独立服务

**Feature Branch**: `006-extract-deepresearch-service`

**Created**: 2026-10-15

**Status**: Draft

**Input**: User description: "把DeepResearch功能从系统中抽取出来，在跟目录单独创建一个目录，与agentrl类似，因为DeepResearch是独立的功能"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - DeepResearch 作为独立服务独立运行 (Priority: P1)

作为维护这个项目的开发者，我希望 DeepResearch（主题规划→并行搜索总结→合成带引用报告）像
AgentRL 一样是仓库根目录下一个完全独立的目录，拥有自己的依赖声明和运行时，不依赖
`apps/api` 的任何代码（模型调用/网页搜索这两项能力通过 path dependency 复用仓库里已有的
`packages/ai`/`packages/websearch`，见 Clarifications），这样它可以独立开发、独立测试、独
立部署，也不会把自己专属的其余依赖掺进主聊天服务的依赖树里。

**Why this priority**: 这是用户明确提出的核心诉求——没有这一步，后续"独立运行""独立数据"都
无从谈起。

**Independent Test**: 在全新克隆的仓库里，只进入新目录执行"安装依赖 + 启动服务"两步，不启动
`apps/api`/`apps/web` 的情况下，服务能独立跑通一次完整的研究流程（创建任务→轮询/订阅进度→
拿到最终报告），且该目录下没有任何 `from db import`/`from runtime import` 这类指向 `apps/
api` 的 import（指向 `packages/ai`/`packages/websearch` 的 import 允许存在，这是 path
dependency 复用方式的预期形态）。

**Acceptance Scenarios**:

1. **Given** 一个全新 clone 的仓库（未启动任何其他服务），**When** 开发者只在新的 DeepResearch
   目录下执行它自己的依赖安装和启动命令，**Then** 服务在自己的端口上监听并通过健康检查。
2. **Given** DeepResearch 服务已独立启动，**When** 调用方发起一次创建研究任务的请求，**Then**
   服务完整走完规划→并行搜索总结→合成报告的流程并返回/推送最终结果，全程不经过
   `apps/api` 进程。
3. **Given** 一份新目录下的代码清单，**When** 静态检查它的 import 语句，**Then** 不存在任何指
   向 `apps/api` 或除 `packages/ai`/`packages/websearch` 之外其他 `packages/*`（如
   `packages/memory`/`packages/core`/`packages/agents`）的 import（允许标准库、PyPI 三方
   包、`packages/ai`/`packages/websearch`、以及自己目录内部的相对 import）。

---

### User Story 2 - 现状的一键启动脚本原样纳管新服务 (Priority: P2)

作为开发者，我希望现状 `scripts/start.sh` 的一键启动/一键停止体验不因为这次抽取而退化——新
目录应该像 AgentRL 一样被纳入同一个启动脚本，装不上/起不来时只警告跳过，不拖垮其余服务。

**Why this priority**: 维持现状的开发体验是"抽取重构"类任务的基本要求——不能让主流程变得更
麻烦。

**Independent Test**: 执行一次 `scripts/start.sh`，确认输出里包含新服务的地址一行，且
`scripts/start.sh stop` 能连带停掉它；人为让新目录的依赖安装失败，确认其余服务仍然正常启动、
只是打印警告。

**Acceptance Scenarios**:

1. **Given** 开发者执行现状的一键启动命令，**When** 启动完成，**Then** 输出里出现新 DeepResearch
   服务的地址，和 AgentRL 那一行一样的格式。
2. **Given** 新目录的依赖因为平台限制装不上，**When** 执行一键启动，**Then** 该服务被跳过并打
   印警告，其余服务（web/api/agentrl/a2apeer）仍然正常起来，一键启动命令本身不报错退出。

---

### User Story 3 - Web 前端继续可用，指向新地址 (Priority: P3)

作为使用这个 Web 应用的用户，我希望 DeepResearch 页面的新建研究任务、查看进度、查看历史、删
除这些操作在抽取之后继续可用，只是请求的目标地址换成了新的独立服务。

**Why this priority**: 面向最终用户的可见功能不能因为内部重构而中断，但这是在前两步完成之后
才有意义的收尾工作。

**Independent Test**: 新服务独立启动后，在浏览器里打开 DeepResearch 页面，新建一个研究任务，
确认进度实时更新、最终报告正常展示、历史列表和删除操作都正常工作，且这些请求全部落在新服务
的端口上（不再经过 `apps/api` 的 `/api/deepresearch/*` 路由）。

**Acceptance Scenarios**:

1. **Given** 新 DeepResearch 服务和 Web 前端都已启动，**When** 用户在页面上发起一个新的研究主
   题，**Then** 页面展示的创建请求、进度推送、最终报告都来自新服务的地址。
2. **Given** 新服务未启动，**When** 用户打开 DeepResearch 页面，**Then** 页面优雅降级提示"服
   务未启动"，不是一个未处理的异常或白屏（与 AgentRL 页面现状的降级体验一致）。

### Edge Cases

- 新服务启动时数据库文件不存在：自动建表，和现状 `ChatStore`/AgentRL 的 `RunStore` 行为一致。
- 新服务和 `apps/api` 同时运行、各自独立但共享同一份根 `.env` 里的模型/搜索密钥时，两边各自
  读取、互不干扰（不要求进程间同步配置）。
- 一次研究任务执行到一半时新服务被重启：按现状行为处理（运行中的任务状态保留在它自己的数据
  库里，重启后不自动续跑，这和 `apps/api` 现状的 "DeepResearch 没有断点续跑" 行为一致，不是
  本次抽取引入的新限制）。

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: 系统 MUST 在仓库根目录新增一个独立目录（非 `apps/`、非 `packages/` 之下，与
  `agentrl/` 同级），承载 DeepResearch 的全部服务端代码（规划/并行搜索总结/报告合成/进度推
  送/任务存取）。
- **FR-002**: 新目录 MUST 拥有自己的依赖声明和可独立安装的运行环境（镜像 `agentrl/
  pyproject.toml` 的组织方式：独立的 `[project.dependencies]` + 独立可安装 `uv sync`/独立启
  动），不依赖仓库根 `pyproject.toml`、不依赖 `apps/api` 目录下的任何 Python 模块；模型调用
  与网页搜索这两项能力通过 uv 的 path dependency 直接依赖仓库里现有的 `packages/ai`/
  `packages/websearch`（见 Clarifications），不重复实现一遍协议/重试/多厂商适配逻辑。
- **FR-003**: 新目录 MUST 提供自己的 HTTP 服务入口（`main.py` 风格，FastAPI + 独立端口），对
  外暴露"创建研究任务/查询任务/查询任务列表/订阅实时进度/删除任务"这组现状能力，行为（字段、
  状态流转、报告格式）与抽取前逐字一致；路由路径 MUST 镜像 AgentRL 的扁平约定（`POST /runs`、
  `GET /runs`、`GET /runs/{id}`、`GET /runs/{id}/stream`、`DELETE /runs/{id}`），不带
  `/api` 或 `deepresearch` 前缀（见 Clarifications）。
- **FR-004**: 新目录 MUST 拥有自己的持久化存储（独立数据库文件，不与 `apps/api` 的
  `chat.db` 共用），现状 `deepresearch_runs` 表的字段与查询需求原样保留。
- **FR-005**: `apps/api` MUST 删除现状的 DeepResearch 路由、`deepresearch.py` 模块、
  `deepresearch_runs` 表定义与相关 CRUD 方法——不保留任何转发/代理层，调用方直接访问新服务。
  `apps/api` 现有 `chat.db` 里 `deepresearch_runs` 表的既有历史数据不要求迁移（见
  Clarifications）——新服务从空数据库起步，旧历史记录留在 `chat.db` 里不再可见，但不主动删
  除那些行。
- **FR-006**: `scripts/start.sh` MUST 把新服务纳入统一的启动/停止/健康检查流程，镜像现状
  AgentRL 的接入方式（独立端口、依赖安装失败时警告并跳过、不拖垮其余服务）。
- **FR-007**: Web 前端 MUST 更新为请求新服务的地址（新增一个类似 `NEXT_PUBLIC_AGENTRL_URL`
  的环境变量）和新的扁平路由路径（`lib/deepresearch-api.ts` 的请求路径从 `/api/
  deepresearch/runs` 改为 `/runs`），现状的创建/列表/详情/实时进度/删除交互对最终用户保持
  不变。
- **FR-008**: 新服务 MUST 能独立调用大语言模型完成"规划子任务/总结搜索结果/合成报告"这三步，
  和独立调用网页搜索完成"按子任务查询"这一步——通过 uv 的 path dependency 直接依赖仓库里现
  有的 `packages/ai`（模型客户端）和 `packages/websearch`（搜索客户端）获得这两项能力，不重
  新实现一遍协议/重试/多厂商适配逻辑（见 Clarifications）。
- **FR-009**: 系统 MUST 为新目录新增与抽取前等价的自动化测试（覆盖规划失败/部分搜索失败/报
  告合成失败/SSE 断线重连/删除运行中任务被拒绝等现状已覆盖的场景），且这些测试独立运行（不
  依赖 `apps/api` 或 `packages/ai`/`packages/websearch` 之外其他 `packages/*` 的测试夹具）。

### Key Entities

- **ResearchRun**：一次研究任务。字段与现状 `deepresearch_runs` 表一致：id、创建时间、状态
  （运行中/已完成/失败）、研究主题、子任务清单（含各自的状态/总结/来源）、最终报告、失败信
  息。
- **ResearchTodo**：ResearchRun 内部的一个子任务（搜索查询问题、执行状态、总结文本、来源列
  表），现状内嵌在 `ResearchRun.todos` 字段里，抽取后结构不变。

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 在完全不启动 `apps/api`/`apps/web` 的情况下，新服务能独立完成一次端到端的研究
  任务（从创建到拿到最终报告）。
- **SC-002**: 一键启动脚本执行后，新服务的健康检查在 10 秒内变绿（参照 `apps/api`/`a2apeer`
  这类轻量 FastAPI 服务现状的启动速度，不是需要装 torch 的 AgentRL 那个量级）。
- **SC-003**: 抽取完成后，针对同一个研究主题，端到端耗时（从创建任务到拿到最终报告）相对抽
  取前的波动不超过 20%。
- **SC-004**: 抽取完成后，`apps/api` 不再包含 `deepresearch.py` 模块、相关路由与
  `deepresearch_runs` 表（`apps/api` 对 `packages/websearch` 的依赖继续保留——这是聊天 Agent
  自身网页搜索工具的既有依赖，与 DeepResearch 无关，不受本次抽取影响）。
- **SC-005**: 新目录下的自动化测试套件可以在不启动 `apps/api`/`apps/web` 进程的前提下独立跑
  通，覆盖率相对抽取前的 `tests/apps/api/test_deepresearch.py` 不降低。

## Clarifications

### Session 2026-10-15

- Q: 新目录完全独立（镜像 AgentRL：自己的 `pyproject.toml`、自己的虚拟环境）之后，DeepResearch
  需要的大模型调用和网页搜索这两项能力具体怎么获得？ → A: 通过 uv 的 path dependency 直接依
  赖仓库里现有的 `packages/ai`（模型客户端）和 `packages/websearch`（搜索客户端），不重复实
  现一遍协议/重试/多厂商适配逻辑；新目录依然保持"自己的 `pyproject.toml`、自己的虚拟环境、
  可以独立 `uv sync` + 独立启动"的独立性，只是这两处具体实现通过路径依赖复用主仓库已有代
  码，不是把全部实现复制一份。
- Q: `apps/api` 的 `chat.db` 里已经存在的历史 DeepResearch 研究记录，抽取成独立服务之后怎么
  处理？ → A: 不迁移，视为可接受的损耗——新服务从空数据库起步，旧历史记录留在 `chat.db`
  里，不主动删除那些行，但用户在新服务里看不到它们。
- Q: 新独立服务对外暴露的 HTTP 路由路径应该长什么样子？ → A: 模仿 AgentRL 的扁平路径（`/runs`
  系列，不带 `/api` 或 `deepresearch` 前缀），不沿用现状 `apps/api` 的 `/api/deepresearch/*`
  形状。
- Q: SC-002/SC-003 的定性描述要不要换成具体数字？ → A: 换成具体数字——SC-002 改为"10 秒内健
  康检查变绿"，SC-003 改为"端到端耗时波动不超过 20%"。

## Assumptions

- Web 前端页面本身（`apps/web/app/deepresearch/page.tsx`）继续留在 `apps/web` 内，只是把请
  求目标地址从 `API_URL`（`apps/api`）换成新的独立服务地址——这正是 AgentRL 页面现状的做法
  （页面留在 `apps/web`，`AGENTRL_URL` 指向独立的 `:8420`），本次 DeepResearch 的前端沿用同
  一模式，不额外询问。
- 新服务的端口号选用仓库里当前未被占用的下一个（`8440`），具体数值由实现阶段确认，不影响本
  spec 的范围判断。
- 新服务和其余服务一样，从仓库根目录的同一份 `.env` 文件里读取所需的模型/搜索密钥环境变量
  （不要求用户为新服务单独配置一份密钥）。
- 新服务是否需要支持"进程重启后自动恢复仍在运行的任务"不在本次范围内——沿用抽取前的现状行
  为（不支持断点续跑）。

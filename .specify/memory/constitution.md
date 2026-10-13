<!--
Sync Impact Report
- Version change: TEMPLATE (unratified) → 1.0.0
- Modified principles: none (first-time ratification, not a rename)
- Added principles:
  - I. 测试驱动开发（TDD，不可协商）
  - II. 代码规范一致性（ESLint / 统一代码风格）
  - III. 输入必须校验
  - IV. 简洁至上，拒绝过度工程（YAGNI）
  - V. 接口文档完整性
- Added sections: 技术栈与质量门禁 (Quality Gates), 开发工作流 (Development Workflow), Governance
- Removed sections: none
- Deferred placeholders: none — all template slots filled with concrete content derived from the
  user's stated principles plus existing repo context (user's global coding-style/testing/
  git-workflow rules, this project's CLAUDE.md, and conventions already practiced in-session).
- Templates requiring follow-up: none checked in this pass — dependent Spec Kit commands
  (speckit-plan/speckit-tasks/speckit-implement) read this constitution at runtime; no edits made
  to them per this command's scope guard.
-->

# OpenTalos Constitution

## Core Principles

### I. 测试驱动开发（TDD，不可协商）
任何业务代码变更前必须先写测试；测试必须先失败（RED），再实现到测试通过（GREEN），再在测试保护下重构
（REFACTOR）。所有业务逻辑代码（`packages/*`、`apps/*` 的核心路由与服务层）必须配套单元测试；不允许提交
没有对应测试覆盖的新业务逻辑。禁止为了让测试通过而反向修改断言本身（测试本身写错的情况除外）；修复 bug
时必须先写一个能复现问题的失败测试，再修复实现。

**理由**：本仓库已经在实践的 brainstorming→spec→plan→TDD 工作流证明了先写测试能在早期自我审查阶段就发现
设计缺陷（例如 `AsyncOpenAI(api_key=None)` 会在构造时立即抛错这类问题），测试是变更正确性唯一可验证的证据。

### II. 代码规范一致性（ESLint / 统一代码风格）
前端 TypeScript/JavaScript 代码必须通过 ESLint 检查，不允许新增 lint 报错或警告被忽略提交。后端 Python
代码遵循 PEP 8，用 ruff/black 风格保持一致（以仓库 `pyproject.toml` 中已配置的规则为准）。引入新文件或新
依赖前先检查是否已有同类工具可用，不重复造轮子。

**理由**：统一的静态检查是团队协作和 AI 辅助编码最低成本的一致性保障，能把 code review 的精力从风格问题
上解放出来，聚焦到正确性和设计上。

### III. 输入必须校验
所有系统边界（HTTP API 请求体、用户输入、外部服务返回的数据、文件上传内容）必须在进入业务逻辑前完成校
验；后端优先用 Pydantic 模型做 schema 校验，前端用 TypeScript 类型 + 运行时校验（如 Zod）兜底。校验失败
必须给出清晰的错误信息（对应的 4xx 状态码 + 可读的 detail），不得让未校验的数据静默污染下游状态。内部可
信边界内（同一进程内、已经校验过的数据）不需要重复校验。

**理由**：系统边界是故障和安全漏洞最常发生的位置；内部数据重复校验则是不必要的过度防御，与原则 IV 的
"拒绝过度工程"互为补充，二者共同划定校验应该发生在哪里、不应该发生在哪里。

### IV. 简洁至上，拒绝过度工程（YAGNI）
只实现当前需求明确要求的功能，不为假设中的未来需求预留抽象、配置项或灵活性。只被使用一次的逻辑不做抽象
封装；三行相似代码优于一个过早的抽象。修改既有代码时只改动任务所需的部分，不顺手重构无关代码。文件保持
短小聚焦（典型 200-400 行，最多 800 行），函数保持单一职责（通常 <50 行）。

**理由**：代码的可读性和可维护性来自于它能被完整地放进一个人（或一次 AI 推理）的工作记忆里；过早引入的
灵活性往往猜错方向，之后要么被废弃、要么成为后来者理解代码的负担。

### V. 接口文档完整性
所有对外暴露的接口（HTTP API 路由、对外函数/类的公共方法、CLI 命令）必须有文档说明其用途、参数、返回值
和错误情况。后端路由至少要有清晰的请求/响应模型（Pydantic Body/Response 定义本身即是文档的一部分），必
要时补充简短 docstring 说明非显而易见的边界行为（如校验顺序、错误码含义）。文档必须随接口变更同步更新；
发现文档与实现脱节时视为缺陷，需要修复而不是忽略。

**理由**：接口是模块之间、团队成员之间、以及 AI 代理与代码库之间协作的契约；没有文档的接口会把理解成本
转嫁给每一个后来的调用者。

## 技术栈与质量门禁 (Quality Gates)

- 测试覆盖率：新增或修改的业务逻辑代码，单元测试覆盖率不低于 80%。
- 后端：Python + pytest，统一用项目虚拟环境运行测试（`.venv/bin/pytest`），不使用系统全局 Python。
- 前端：TypeScript + Vitest，ESLint + Prettier 作为格式化与规范检查工具。
- 提交前必须本地跑通受影响范围的测试套件；影响面不确定时跑全量测试套件。
- 禁止提交包含硬编码密钥、API Key、密码等敏感信息的代码；密钥一律通过环境变量管理。

## 开发工作流 (Development Workflow)

- 新功能或非 trivial 变更遵循"需求澄清 → 方案设计 → 编写实现计划 → TDD 落地（红-绿-重构）→ 全量回归 →
  真机验证 → 提交"的流程；设计文档可按项目既有约定存放在本地，不强制纳入版本库。
- 提交信息遵循 `<type>: <description>` 格式（feat/fix/refactor/docs/test/chore/perf/ci），每个提交聚焦
  单一变更。
- 代码评审聚焦正确性、安全性与可维护性，而非风格偏好（风格已由 ESLint/格式化工具保证）。
- 涉及安全敏感代码（鉴权、支付、用户数据、文件系统操作）的改动必须额外做安全性检查。

## Governance

本宪法的效力高于项目内的其他非正式约定；当两者冲突时以本文件为准。任何对核心原则的新增、删除或重新定
义，必须在本文件中记录修订并提升版本号；仅修订措辞或补充说明不升主版本号。

版本策略：
- **MAJOR**：删除或不兼容地重新定义已有原则。
- **MINOR**：新增原则，或新增实质性章节内容。
- **PATCH**：措辞澄清、拼写修正等非语义变更。

所有代码评审/合并前需要对照本宪法做一次合规性检查；复杂度的引入必须在评审中给出明确理由（对应原则 IV）。

**Version**: 1.0.0 | **Ratified**: 2026-10-13 | **Last Amended**: 2026-10-13

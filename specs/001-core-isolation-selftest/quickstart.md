# Quickstart: 验证"Agent Loop 核心边界隔离 + 真实模型自测"

本指南给出实现完成后、`/speckit-implement` 收尾时应该跑一遍的端到端验证步骤，对应 spec.md 的三条
User Story。Protocol 的精确方法签名见 [data-model.md](./data-model.md)，边界检查脚本的调用约定见
[contracts/boundary-check-cli.md](./contracts/boundary-check-cli.md)。

## 前置条件

- 已执行 `uv sync`（或 `.venv/bin/pip install -e .`），`.venv/bin/pytest` 可用。
- 如果要验证真实模型自测的"通过"路径（而不只是"正确跳过"路径），`.env` 里需要配置好
  `MODEL_PROVIDER`/`MODEL_API_KEY`/`MODEL_NAME`（参考仓库根目录 `.env.example`）。没有配置也能跑
  完本指南的其余部分——对应的那一步会显示跳过而不是失败。

## 场景 1：边界检查——当前代码应该是干净的（User Story 1 + 2）

```bash
.venv/bin/python scripts/check_core_boundary.py
```

**预期**：退出码 `0`，输出 `OK: packages/core 未依赖任何其他 packages/* 目录`。

## 场景 2：边界检查能抓到人为引入的违规（User Story 2 的 Acceptance Scenario 2）

```bash
echo "from tool.registry import ToolRegistry  # 临时验证用，之后删掉" >> packages/core/errors.py
.venv/bin/python scripts/check_core_boundary.py; echo "退出码: $?"
git checkout -- packages/core/errors.py   # 验证完立刻撤销这行临时改动
```

**预期**：退出码 `1`，输出里能看到 `packages/core/errors.py:<行号>: 导入了 "tool"`。

## 场景 3：常规测试套件里自动包含边界检查（User Story 2，不依赖手动调用脚本）

```bash
.venv/bin/pytest tests/test_check_core_boundary.py -v
```

**预期**：全部 PASS，且其中一个测试用例是直接调用
`check_core_boundary.find_boundary_violations(Path("packages/core"))` 断言返回空列表（不经过子进
程调用 CLI）。

## 场景 4：`packages/core` 的既有单元测试全部保持通过（回归，不是新场景）

```bash
.venv/bin/pytest tests/core/ -v
```

**预期**：全部 PASS——这次改动是纯粹的依赖注入重构，`Agent`/`agent_loop` 对外可观察的行为（给定
同样的 mock 模型和同样的输入，产出同样的回复）不应该发生任何变化。

## 场景 5：真实模型自测——未配置凭据时的降级路径（User Story 3 的 Acceptance Scenario 2）

```bash
unset MODEL_API_KEY  # 确保当前 shell 没有残留的真实凭据
.venv/bin/pytest tests/core/test_real_model_selftest.py -v
```

**预期**：测试显示为 `SKIPPED`，原因文本里能看到"未配置 MODEL_API_KEY，跳过真实模型自测"这类清楚
的说明，而不是报错或者直接通不过。

## 场景 6：真实模型自测——已配置凭据时真正跑通（User Story 3 的 Acceptance Scenario 1）

```bash
# 确保 .env 里已经配置好 MODEL_PROVIDER/MODEL_API_KEY/MODEL_NAME
.venv/bin/pytest tests/core/test_real_model_selftest.py -v -s
```

**预期**：测试显示为 `PASSED`，`-s` 模式下能在终端看到这次真实模型调用返回的文本内容（用于人工确
认这确实是一次真实往返，不是误报的绿色）。整个测试应该在 60 秒内结束（对应 SC-003）。

## 场景 7：侧向确认——其他功能包仍然能正常驱动 agent loop

```bash
.venv/bin/pytest tests/agents/ tests/apps/api/ -v
```

**预期**：全部 PASS——`packages/agents`/`apps/api/runtime.py` 这两个调用方改成"构造 Protocol 实现
再注入"之后，行为对最终用户（HTTP API 的调用者）必须完全无感知，这组既有测试就是最直接的回归证
据。

# Quickstart: 验证"独立的 Provider 包 + Web 端配置界面"

> 本文档在 `/speckit-plan` 阶段写出，描述实现完成后应该怎么验证；命令里引用的测试文件名/测
> 试函数名以 `/speckit-tasks` 最终产出的 `tasks.md` 为准。

## 前置条件

```bash
cd /Users/arron/Desktop/ArronAI/OpenTalos
.venv/bin/pytest --version
cd apps/web && npx vitest --version && cd ../..
```

## 场景 1：`packages/core` 边界零违规 + 004 feature 行为逐字不变（User Story 1）

```bash
.venv/bin/python scripts/check_core_boundary.py
.venv/bin/pytest tests/ai/ -v   # 004 feature 测试原样搬到新目录后重新跑
.venv/bin/pytest tests/core/ -v  # agent.py/agent_loop.py 改类型标注后现状测试不受影响
```

预期：边界检查器报告零违规；两组测试全部通过，断言内容和搬移前完全一致。

## 场景 2：具名 provider 快捷新增 + 自定义新增 + 激活互斥（User Story 2）

```bash
.venv/bin/pytest tests/apps/api/test_db.py -k provider_config -v
.venv/bin/pytest tests/apps/api/test_api_routes.py -k provider -v
```

预期：新增一条配置后数据库存明文、API 响应里密钥已掩码；激活一条后同 purpose 下原本激活的
那条自动取消。

## 场景 3：聊天配置免重启生效（User Story 2）

```bash
.venv/bin/pytest tests/apps/api/test_runtime.py -k provider_config -v
```

预期：激活一条配置后，新建的下一个任务使用它；已经缓存的任务不受影响；删除/取消激活后回退
到环境变量配置。

## 场景 4：Embedding 配置免重启生效（User Story 3）

```bash
.venv/bin/pytest tests/apps/api/test_db.py -k embedding -v
.venv/bin/pytest tests/memory/test_semantic.py -k embedder_factory -v
```

预期：`SemanticMemory` 每次都通过工厂函数重新拿 `EmbeddingClient`；激活/取消激活 embedding
配置后，下一次 `embed()` 调用反映最新配置。

## 场景 5：前端页面 + 侧边栏入口

```bash
cd apps/web && npx vitest run app/providers/page.test.ts
```

```bash
# 真机验证（需要 apps/api :8400 + apps/web :3010 都在跑）：
# 1. 打开 http://localhost:3010/，确认侧边栏展开态和折叠态都能看到 Provider 入口
# 2. 点击进入 /providers，确认能看到 chat/embedding 两个分组 + 具名 provider 快捷卡片
# 3. 用快捷卡片新增一条配置并激活，确认列表里显示为激活状态、密钥已掩码
# 4. 新建一个对话任务，确认用的是刚激活的配置（可以用一个明显不同的模型名辨认）
```

## 场景 6：安全检查（research.md 决策 9）

```bash
grep -rn "api_key" apps/api/main.py apps/api/db.py | grep -v "api_key_masked\|api_key:"
# 人工核实每一处 api_key 相关代码路径，确认没有任何地方把完整密钥写进日志/trace/错误信息
```

## 场景 7：全量回归

```bash
.venv/bin/pytest
.venv/bin/python scripts/check_core_boundary.py
cd apps/web && npx vitest run
```

预期：全量测试通过，测试数相比改动前只增不减；边界检查器零违规。

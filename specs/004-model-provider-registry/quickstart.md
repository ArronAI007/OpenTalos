# Quickstart: 验证"对齐 pi 的统一模型 Provider 功能"

> 本文档在 `/speckit-plan` 阶段写出，描述实现完成后应该怎么验证；命令里引用的测试文件名/测试
> 函数名以 `/speckit-tasks` 最终产出的 `tasks.md` 为准（规划阶段按 Project Structure 的文件布
> 局预先起名，若实现时调整了命名，请同步更新这里）。

## 前置条件

```bash
cd /Users/arron/Desktop/ArronAI/OpenTalos
.venv/bin/pytest --version   # 确认用的是项目虚拟环境，不是系统/anaconda 的 python
```

## 场景 1：具名 provider 的密钥/base_url 自动解析（User Story 1）

```bash
.venv/bin/pytest tests/core/test_providers.py -v
```

预期：未注册的 provider 名字在构造阶段就抛 `SettingsError`，错误信息列出全部可用名字；具名
provider 专属环境变量优先于通用 `MODEL_API_KEY`；只设置通用 `MODEL_API_KEY`（不设任何专属变
量）时行为和改动前完全一致；显式 `base_url`/`MODEL_BASE_URL` 覆盖 provider 默认服务地址。

```bash
.venv/bin/pytest tests/core/test_model.py -v
```

预期：现状 `anthropic`/`openai-compatible`/`mock` 的全部既有测试用例继续通过（不回归）。

## 场景 2：模型能力目录 + 压缩阈值默认值（User Story 2）

```bash
.venv/bin/pytest tests/core/test_model_catalog.py -v
```

预期：已登记模型返回完整能力数据；未登记模型返回 `None`；
`default_compaction_token_limit` 对已知模型返回"上下文窗口 × 0.5"，对未知模型返回 16000（和
改动前 `apps/api/main.py` 的硬编码默认值一致）。

```bash
.venv/bin/pytest tests/apps/api/test_runtime.py -k compaction -v
```

预期：不传 `compaction_token_limit`、`model_name` 命中目录时，实际生效的压缩阈值来自目录换
算；显式传值时优先于目录数据；模型未知时回退到 16000。

## 场景 3：流式用量上报的声明式配置（User Story 3）

```bash
.venv/bin/pytest tests/core/test_model.py -k DeclarativeProviderQuirks -v
```

预期：声明 `supports_stream_usage=False` 的（测试专属合成）provider，首次流式请求就不带
`stream_options`，不经历"先失败一次再降级"；现状 `openai-compatible`（未声明）继续保留反应
式学习行为。

## 场景 4：全量回归

```bash
.venv/bin/pytest
.venv/bin/python scripts/check_core_boundary.py
```

预期：全量测试通过，测试数相比改动前只增不减；`packages/core` 边界检查器保持零违规（新增的
`providers.py`/`model_catalog.py` 都不 import 其他 `packages/*`）。

## 场景 5：`.env.example` 文档更新核查（SC-001）

```bash
grep -n "DEEPSEEK_API_KEY\|OPENAI_API_KEY\|MOONSHOT_API_KEY" .env.example
```

预期：新增具名 provider 的专属环境变量名都有文档说明，用户不需要翻源码就知道换 provider 该设
哪个变量名。

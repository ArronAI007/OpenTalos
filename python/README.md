# OpenTalos — Python 核心

Agent 核心（GraphEngine、持久化层、model provider、chat-agent、scheduler、api）的 Python 重写。
详见 `docs/superpowers/specs/2026-09-20-python-core-rewrite-design.md`。

## 开发

```bash
uv sync
uv run pytest
```

## 进度

- [x] 阶段 1：基础层（core_types、checkpoint、tracing、tool_registry，含 Postgres RLS）
- [ ] 阶段 2：GraphEngine
- [ ] 阶段 3：model_providers + sdk
- [ ] 阶段 4：chat_agent
- [ ] 阶段 5：scheduler + worker
- [ ] 阶段 6：api
- [ ] 阶段 7：apps/web 适配
- [ ] 阶段 8：整体联调 + 切换

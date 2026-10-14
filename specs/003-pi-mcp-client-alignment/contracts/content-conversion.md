# Contract: 工具调用结果到模型内容的转换（`to_llm_content` + `MCPTool.acall()`）

对应 User Story 4（后半）、FR-006、SC-005。

## `protocol/content.py` 层

```python
def to_llm_content(result: CallToolResult) -> list[LlmContent]: ...
```

1. `content` 非空时逐个 block 转换：`text`→`TextLlmContent` 原样透传；`image`→
   `ImageLlmContent` 原样透传；嵌入的文本资源（`resource` block 内层是 `TextResourceContents`）
   解包成 `TextLlmContent`；嵌入的图片资源（`BlobResourceContents` 且 `mime_type` 是
   `image/*`）解包成 `ImageLlmContent`；`audio`/`resource_link`/其余二进制 `resource` 转成简短
   的 `TextLlmContent` 占位符（必须是人类可读的一句话描述，不能是 Python 对象的默认 repr）。
2. `content` 为空、`structured_content` 非空：返回恰好一个 `TextLlmContent`，内容是
   `structured_content` 的 JSON 文本（`ensure_ascii=False`）。
3. 两者都为空：返回空列表。
4. 不改变现状对"纯文本 `CallToolResult`"的转换结果（User Story 4 Acceptance Scenario 2 的不回归
   要求）——即 `to_llm_content` 对一个只有文本 block 的输入，拼接结果必须和现状
   `"\n".join(block.text for block in result.content)` 的行为等价。

## `tools.py` 层（`MCPTool.acall()` 的压平规则，不属于 `to_llm_content` 本身）

`acall()` 调用 `to_llm_content(result)` 后，把 `list[LlmContent]` 压平成 `ToolOutcome.output`
需要的单个 `str`：

- 多个 `TextLlmContent` 之间用 `"\n"` 连接。
- 每个 `ImageLlmContent` 转成一行占位符：`f"[图片内容：{mime_type}，约 {len(data)} 字符的
  base64 数据]"`（必须包含 `mime_type`，不能是 `str(content_block)` 这种对象默认字符串化）。
- 最终字符串非空即视为 `ToolOutcome.ok(...)`；`result.is_error` 为真时仍然构造同样的压平文本，
  但通过 `MCPConnectionError`（"tool call returned an error: ..."）的现状路径转成
  `ToolOutcome.error(...)`，不改变现状的错误处理分支结构。

## 独立测试方式

- 单测 `to_llm_content`：构造纯文本 / 纯图片 / 混合（文本+嵌入图片资源）/ 仅
  `structured_content` 四种 `CallToolResult`，断言各自的 `list[LlmContent]` 形状。
- 单测 `MCPTool.acall()` 的压平：mock 一个返回图片内容的 `CallToolResult`（不需要真实连接），断
  言最终 `ToolOutcome.output` 字符串里包含可读的 `mime_type` 占位符，不包含 Python 对象 repr 的
  典型特征（如 `<` 和内存地址 `0x...`）。
- 真机：`demo_server.py` 现状只返回纯文本（天气字符串），不需要改造成返回图片就能验证"不回
  归"这一条；图片/嵌入资源场景用内存传输配一个假服务端 handler 覆盖（不依赖 `demo_server.py`
  新增图片工具）。

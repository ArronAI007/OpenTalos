"""工具调用结果的内容类型（`CallToolResult`/`ContentBlock`/`LlmContent`）。

本文件只放类型定义；`to_llm_content()` 转换函数在 User Story 4 阶段实现（见
contracts/content-conversion.md），避免这个 Foundational 阶段的任务提前掺进业务逻辑。
"""
from dataclasses import dataclass
from typing import Literal


@dataclass
class TextResourceContents:
    uri: str
    mime_type: str | None
    text: str


@dataclass
class BlobResourceContents:
    uri: str
    mime_type: str | None
    blob: str  # base64


@dataclass
class TextContentBlock:
    text: str
    type: Literal["text"] = "text"


@dataclass
class ImageContentBlock:
    data: str  # base64
    mime_type: str
    type: Literal["image"] = "image"


@dataclass
class AudioContentBlock:
    data: str  # base64
    mime_type: str
    type: Literal["audio"] = "audio"


@dataclass
class ResourceLinkContentBlock:
    uri: str
    name: str
    type: Literal["resource_link"] = "resource_link"


@dataclass
class EmbeddedResourceContentBlock:
    resource: TextResourceContents | BlobResourceContents
    type: Literal["resource"] = "resource"


ContentBlock = (
    TextContentBlock
    | ImageContentBlock
    | AudioContentBlock
    | ResourceLinkContentBlock
    | EmbeddedResourceContentBlock
)


@dataclass
class CallToolResult:
    content: list[ContentBlock]
    structured_content: dict | None = None
    is_error: bool = False


def _resource_contents_from_wire(data: dict) -> "TextResourceContents | BlobResourceContents":
    if "text" in data:
        return TextResourceContents(uri=data["uri"], mime_type=data.get("mimeType"), text=data["text"])
    return BlobResourceContents(uri=data["uri"], mime_type=data.get("mimeType"), blob=data.get("blob", ""))


def _content_blocks_from_wire(blocks: list[dict]) -> list[ContentBlock]:
    """把 `tools/call` 响应里原始的 `content` 数组解析成 `ContentBlock` dataclass 列表。
    这是协议层的"反序列化"，不是 `to_llm_content()` 那个面向模型的转换（二者职责不同：这里只
    负责把 wire 格式的 dict 变成类型化对象，`to_llm_content` 才决定怎么呈现给模型）。"""
    parsed: list[ContentBlock] = []
    for block in blocks:
        block_type = block.get("type")
        if block_type == "text":
            parsed.append(TextContentBlock(text=block.get("text", "")))
        elif block_type == "image":
            parsed.append(ImageContentBlock(data=block.get("data", ""), mime_type=block.get("mimeType", "")))
        elif block_type == "audio":
            parsed.append(AudioContentBlock(data=block.get("data", ""), mime_type=block.get("mimeType", "")))
        elif block_type == "resource_link":
            parsed.append(ResourceLinkContentBlock(uri=block.get("uri", ""), name=block.get("name", "")))
        elif block_type == "resource":
            parsed.append(EmbeddedResourceContentBlock(resource=_resource_contents_from_wire(block["resource"])))
        else:
            parsed.append(TextContentBlock(text=str(block)))
    return parsed


@dataclass
class TextLlmContent:
    text: str
    type: Literal["text"] = "text"


@dataclass
class ImageLlmContent:
    data: str
    mime_type: str
    type: Literal["image"] = "image"


LlmContent = TextLlmContent | ImageLlmContent

"""工具调用结果的内容类型（`CallToolResult`/`ContentBlock`/`LlmContent`）+ `to_llm_content()`
转换函数（User Story 4，对应 contracts/content-conversion.md）。"""
import json
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


def to_llm_content(result: CallToolResult) -> list[LlmContent]:
    """把 `CallToolResult` 转成模型可读的内容列表（FR-006）：文本/图片直接透传，嵌入的文本/
    图片资源解包，音频/资源链接/其余二进制资源转成简短文本占位符；没有 `content` 但有
    `structured_content` 时用它的 JSON 文本；两者都为空时返回空列表（现状行为的延伸）。"""
    if not result.content:
        if result.structured_content is not None:
            return [TextLlmContent(text=json.dumps(result.structured_content, ensure_ascii=False))]
        return []
    converted: list[LlmContent] = []
    for block in result.content:
        if isinstance(block, TextContentBlock):
            converted.append(TextLlmContent(text=block.text))
        elif isinstance(block, ImageContentBlock):
            converted.append(ImageLlmContent(data=block.data, mime_type=block.mime_type))
        elif isinstance(block, AudioContentBlock):
            converted.append(TextLlmContent(text=f"[音频内容：{block.mime_type}]"))
        elif isinstance(block, ResourceLinkContentBlock):
            converted.append(TextLlmContent(text=f"[资源链接：{block.name} ({block.uri})]"))
        elif isinstance(block, EmbeddedResourceContentBlock):
            converted.append(_embedded_resource_to_llm_content(block.resource))
        else:
            converted.append(TextLlmContent(text=str(block)))
    return converted


def _embedded_resource_to_llm_content(
    resource: "TextResourceContents | BlobResourceContents",
) -> LlmContent:
    if isinstance(resource, TextResourceContents):
        return TextLlmContent(text=resource.text)
    mime_type = resource.mime_type or "application/octet-stream"
    if mime_type.startswith("image/"):
        return ImageLlmContent(data=resource.blob, mime_type=mime_type)
    return TextLlmContent(text=f"[嵌入资源：{mime_type}，约 {len(resource.blob)} 字符的 base64 数据]")

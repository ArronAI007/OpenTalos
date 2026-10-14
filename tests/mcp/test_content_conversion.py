"""to_llm_content() 的单测：四种 CallToolResult 形状（纯文本/图片+嵌入资源/仅 structuredContent/
空结果）的转换结果。"""
import json

from mcp.protocol.content import (
    BlobResourceContents,
    CallToolResult,
    EmbeddedResourceContentBlock,
    ImageContentBlock,
    ImageLlmContent,
    TextContentBlock,
    TextLlmContent,
    TextResourceContents,
    to_llm_content,
)


class TestPureTextNonRegression:
    def test_matches_current_join_behavior(self) -> None:
        result = CallToolResult(content=[TextContentBlock(text="line1"), TextContentBlock(text="line2")])
        converted = to_llm_content(result)
        assert converted == [TextLlmContent(text="line1"), TextLlmContent(text="line2")]


class TestImageAndEmbeddedResources:
    def test_image_block_passes_through(self) -> None:
        result = CallToolResult(content=[ImageContentBlock(data="base64data", mime_type="image/png")])
        converted = to_llm_content(result)
        assert converted == [ImageLlmContent(data="base64data", mime_type="image/png")]

    def test_embedded_text_resource_unpacks_to_text(self) -> None:
        result = CallToolResult(
            content=[
                EmbeddedResourceContentBlock(
                    resource=TextResourceContents(uri="file:///a.txt", mime_type="text/plain", text="hello")
                )
            ]
        )
        converted = to_llm_content(result)
        assert converted == [TextLlmContent(text="hello")]

    def test_embedded_image_resource_unpacks_to_image(self) -> None:
        result = CallToolResult(
            content=[
                EmbeddedResourceContentBlock(
                    resource=BlobResourceContents(uri="file:///a.png", mime_type="image/png", blob="b64bytes")
                )
            ]
        )
        converted = to_llm_content(result)
        assert converted == [ImageLlmContent(data="b64bytes", mime_type="image/png")]

    def test_embedded_binary_non_image_resource_becomes_placeholder(self) -> None:
        result = CallToolResult(
            content=[
                EmbeddedResourceContentBlock(
                    resource=BlobResourceContents(uri="file:///a.bin", mime_type="application/octet-stream", blob="xx")
                )
            ]
        )
        converted = to_llm_content(result)
        assert len(converted) == 1
        assert isinstance(converted[0], TextLlmContent)
        assert "application/octet-stream" in converted[0].text


class TestStructuredContentOnly:
    def test_structured_content_without_content_becomes_json_text(self) -> None:
        result = CallToolResult(content=[], structured_content={"temperature": 21, "city": "Beijing"})
        converted = to_llm_content(result)
        assert len(converted) == 1
        assert isinstance(converted[0], TextLlmContent)
        assert json.loads(converted[0].text) == {"temperature": 21, "city": "Beijing"}


class TestEmptyResult:
    def test_no_content_no_structured_content_returns_empty_list(self) -> None:
        result = CallToolResult(content=[], structured_content=None)
        assert to_llm_content(result) == []

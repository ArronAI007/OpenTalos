"""Helpers for translating canonical OpenAI Chat SSE streams to inbound protocols."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from gateway.inbound_anthropic import AnthropicInboundStreamAdapter
from gateway.inbound_gemini import GeminiInboundStreamAdapter
from gateway.inbound_responses import ResponsesStreamAdapter


async def convert_chat_sse(
    source: AsyncIterator[str],
    *,
    protocol: str,
    requested_model: str,
) -> AsyncIterator[str]:
    if protocol == "openai-chat":
        async for chunk in source:
            yield chunk
        return

    adapter: Any
    if protocol == "openai-responses":
        adapter = ResponsesStreamAdapter(requested_model)
        for event in adapter.start():
            yield _responses_sse(event)
    elif protocol == "anthropic-messages":
        adapter = AnthropicInboundStreamAdapter(requested_model)
        for event_name, data in adapter.start():
            yield _anthropic_sse(event_name, data)
    elif protocol == "gemini":
        adapter = GeminiInboundStreamAdapter(requested_model)
    else:
        raise ValueError(f"unsupported inbound stream protocol: {protocol}")

    finish_reason: str | None = None
    async for event in _openai_events(source):
        if event is None:
            continue
        choice = (event.get("choices") or [{}])[0]
        finish_reason = choice.get("finish_reason") or finish_reason
        if protocol == "openai-responses":
            for translated in adapter.feed(event):
                yield _responses_sse(translated)
        elif protocol == "anthropic-messages":
            for event_name, data in adapter.feed(event):
                yield _anthropic_sse(event_name, data)
        else:
            for translated in adapter.feed(event):
                yield f"data: {json.dumps(translated, separators=(',', ':'))}\n\n"

    if protocol == "openai-responses":
        for translated in adapter.finish(finish_reason):
            yield _responses_sse(translated)
    elif protocol == "anthropic-messages":
        for event_name, data in adapter.finish(finish_reason):
            yield _anthropic_sse(event_name, data)
    else:
        for translated in adapter.finish(finish_reason):
            yield f"data: {json.dumps(translated, separators=(',', ':'))}\n\n"


async def _openai_events(source: AsyncIterator[str]) -> AsyncIterator[dict[str, Any] | None]:
    buffer = ""
    async for chunk in source:
        buffer += chunk
        while "\n\n" in buffer:
            block, buffer = buffer.split("\n\n", 1)
            data_lines = [
                line[5:].strip()
                for line in block.splitlines()
                if line.startswith("data:")
            ]
            if not data_lines:
                continue
            raw = "\n".join(data_lines)
            if raw == "[DONE]":
                yield None
                continue
            try:
                event = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict):
                yield event


def _responses_sse(event: dict[str, Any]) -> str:
    return (
        f"event: {event['type']}\n"
        f"data: {json.dumps(event, separators=(',', ':'))}\n\n"
    )


def _anthropic_sse(event_name: str, data: dict[str, Any]) -> str:
    return (
        f"event: {event_name}\n"
        f"data: {json.dumps(data, separators=(',', ':'))}\n\n"
    )

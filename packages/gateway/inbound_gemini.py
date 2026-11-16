"""Translate Gemini generateContent payloads to canonical Chat payloads."""

from __future__ import annotations

import json
import time
import uuid
from typing import Any


def gemini_request_to_chat(
    payload: dict[str, Any],
    requested_model: str,
) -> dict[str, Any]:
    messages: list[dict[str, Any]] = []
    system = payload.get("systemInstruction") or payload.get("system_instruction")
    if system:
        messages.append({"role": "system", "content": _gemini_text(system.get("parts", []))})
    for content in payload.get("contents", []):
        role = "assistant" if content.get("role") == "model" else "user"
        text_parts: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        tool_results: list[dict[str, Any]] = []
        for part in content.get("parts", []):
            if "text" in part:
                text_parts.append(part["text"])
            if "functionCall" in part:
                call = part["functionCall"]
                tool_calls.append(
                    {
                        "id": f"call_{uuid.uuid4().hex[:10]}",
                        "type": "function",
                        "function": {
                            "name": call.get("name", ""),
                            "arguments": json.dumps(call.get("args", {})),
                        },
                    }
                )
            if "functionResponse" in part:
                result = part["functionResponse"]
                tool_results.append(
                    {
                        "role": "tool",
                        "tool_call_id": result.get("id", result.get("name", "")),
                        "content": json.dumps(result.get("response", {})),
                    }
                )
        if text_parts or tool_calls:
            message: dict[str, Any] = {
                "role": role,
                "content": "".join(text_parts) or None,
            }
            if tool_calls:
                message["tool_calls"] = tool_calls
            messages.append(message)
        messages.extend(tool_results)
    generation = payload.get("generationConfig") or payload.get("generation_config") or {}
    translated: dict[str, Any] = {
        "model": requested_model,
        "messages": messages,
        "stream": False,
    }
    for source, target in (
        ("maxOutputTokens", "max_tokens"),
        ("temperature", "temperature"),
        ("topP", "top_p"),
    ):
        if generation.get(source) is not None:
            translated[target] = generation[source]
    declarations = [
        declaration
        for tool in payload.get("tools", [])
        for declaration in tool.get("functionDeclarations", [])
    ]
    if declarations:
        translated["tools"] = [
            {
                "type": "function",
                "function": {
                    "name": declaration.get("name", ""),
                    "description": declaration.get("description", ""),
                    "parameters": declaration.get("parameters", {"type": "object", "properties": {}}),
                },
            }
            for declaration in declarations
        ]
    return translated


def chat_request_to_gemini(payload: dict[str, Any]) -> dict[str, Any]:
    contents: list[dict[str, Any]] = []
    system_parts: list[str] = []
    for message in payload.get("messages", []):
        role = message.get("role")
        if role == "system":
            system_parts.append(_content_text(message.get("content")))
            continue
        if role == "tool":
            contents.append(
                {
                    "role": "user",
                    "parts": [
                        {
                            "functionResponse": {
                                "name": message.get("tool_call_id", ""),
                                "response": {"content": message.get("content", "")},
                            }
                        }
                    ],
                }
            )
            continue
        parts: list[dict[str, Any]] = []
        text = _content_text(message.get("content"))
        if text:
            parts.append({"text": text})
        for call in message.get("tool_calls", []):
            try:
                arguments = json.loads(call.get("function", {}).get("arguments") or "{}")
            except json.JSONDecodeError:
                arguments = {}
            parts.append(
                {
                    "functionCall": {
                        "name": call.get("function", {}).get("name", ""),
                        "args": arguments,
                    }
                }
            )
        contents.append(
            {
                "role": "model" if role == "assistant" else "user",
                "parts": parts,
            }
        )
    translated: dict[str, Any] = {"contents": contents}
    if system_parts:
        translated["systemInstruction"] = {
            "parts": [{"text": "\n\n".join(system_parts)}]
        }
    generation: dict[str, Any] = {}
    for source, target in (
        ("max_tokens", "maxOutputTokens"),
        ("temperature", "temperature"),
        ("top_p", "topP"),
    ):
        if payload.get(source) is not None:
            generation[target] = payload[source]
    if generation:
        translated["generationConfig"] = generation
    if payload.get("tools"):
        translated["tools"] = [
            {
                "functionDeclarations": [
                    {
                        "name": tool["function"]["name"],
                        "description": tool["function"].get("description", ""),
                        "parameters": tool["function"].get("parameters", {}),
                    }
                    for tool in payload["tools"]
                ]
            }
        ]
    return translated


def chat_response_to_gemini(
    payload: dict[str, Any],
    requested_model: str,
) -> dict[str, Any]:
    choice = (payload.get("choices") or [{}])[0]
    message = choice.get("message", {})
    parts: list[dict[str, Any]] = []
    if message.get("content") is not None:
        parts.append({"text": message["content"]})
    for call in message.get("tool_calls", []):
        try:
            arguments = json.loads(call.get("function", {}).get("arguments") or "{}")
        except json.JSONDecodeError:
            arguments = {}
        parts.append(
            {
                "functionCall": {
                    "name": call.get("function", {}).get("name", ""),
                    "args": arguments,
                }
            }
        )
    usage = payload.get("usage", {})
    prompt_tokens = int(usage.get("prompt_tokens") or 0)
    completion_tokens = int(usage.get("completion_tokens") or 0)
    return {
        "candidates": [
            {
                "content": {"role": "model", "parts": parts},
                "finishReason": _gemini_finish_reason(choice.get("finish_reason")),
                "index": 0,
            }
        ],
        "usageMetadata": {
            "promptTokenCount": prompt_tokens,
            "candidatesTokenCount": completion_tokens,
            "totalTokenCount": int(usage.get("total_tokens") or prompt_tokens + completion_tokens),
        },
        "modelVersion": requested_model,
    }


class GeminiInboundStreamAdapter:
    def __init__(self, requested_model: str) -> None:
        self.requested_model = requested_model

    def feed(self, chunk: dict[str, Any]) -> list[dict[str, Any]]:
        choice = (chunk.get("choices") or [{}])[0]
        delta = choice.get("delta", {})
        parts: list[dict[str, Any]] = []
        if delta.get("content"):
            parts.append({"text": delta["content"]})
        return [
            {
                "candidates": [
                    {
                        "content": {"role": "model", "parts": parts},
                        "index": 0,
                    }
                ],
                "modelVersion": self.requested_model,
            }
        ] if parts else []

    def finish(self, finish_reason: str | None) -> list[dict[str, Any]]:
        return [
            {
                "candidates": [
                    {
                        "content": {"role": "model", "parts": []},
                        "finishReason": _gemini_finish_reason(finish_reason),
                        "index": 0,
                    }
                ],
                "modelVersion": self.requested_model,
            }
        ]


def _gemini_text(parts: list[dict[str, Any]]) -> str:
    return "".join(part.get("text", "") for part in parts if "text" in part)


def _gemini_finish_reason(reason: str | None) -> str:
    return {
        "stop": "STOP",
        "length": "MAX_TOKENS",
        "tool_calls": "STOP",
    }.get(reason or "", "STOP")


def gemini_response_to_chat(payload: dict[str, Any], requested_model: str) -> dict[str, Any]:
    candidate = (payload.get("candidates") or [{}])[0]
    parts = candidate.get("content", {}).get("parts", [])
    text_parts: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    for part in parts:
        if "text" in part:
            text_parts.append(part["text"])
        if "functionCall" in part:
            call = part["functionCall"]
            tool_calls.append(
                {
                    "id": f"call_{uuid.uuid4().hex[:10]}",
                    "type": "function",
                    "function": {
                        "name": call.get("name", ""),
                        "arguments": json.dumps(call.get("args", {})),
                    },
                }
            )
    message: dict[str, Any] = {
        "role": "assistant",
        "content": "".join(text_parts) or None,
    }
    if tool_calls:
        message["tool_calls"] = tool_calls
    usage = payload.get("usageMetadata", {})
    prompt_tokens = int(usage.get("promptTokenCount") or 0)
    completion_tokens = int(usage.get("candidatesTokenCount") or 0)
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": requested_model,
        "choices": [
            {
                "index": 0,
                "message": message,
                "finish_reason": "tool_calls" if tool_calls else _chat_finish_reason(candidate.get("finishReason")),
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": int(usage.get("totalTokenCount") or prompt_tokens + completion_tokens),
        },
    }


def gemini_stream_to_chat(payload: dict[str, Any], requested_model: str) -> dict[str, Any]:
    candidate = (payload.get("candidates") or [{}])[0]
    parts = candidate.get("content", {}).get("parts", [])
    delta: dict[str, Any] = {}
    text = "".join(part.get("text", "") for part in parts if "text" in part)
    if text:
        delta["content"] = text
    tool_calls = []
    for part in parts:
        if "functionCall" in part:
            call = part["functionCall"]
            tool_calls.append(
                {
                    "index": len(tool_calls),
                    "id": f"call_{uuid.uuid4().hex[:10]}",
                    "type": "function",
                    "function": {
                        "name": call.get("name", ""),
                        "arguments": json.dumps(call.get("args", {})),
                    },
                }
            )
    if tool_calls:
        delta["tool_calls"] = tool_calls
    finish = _chat_finish_reason(candidate.get("finishReason"))
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion.chunk",
        "model": requested_model,
        "choices": [
            {
                "index": 0,
                "delta": delta,
                "finish_reason": finish if candidate.get("finishReason") else None,
            }
        ],
    }


def _content_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(
            part.get("text", "")
            for part in value
            if isinstance(part, dict) and part.get("type") == "text"
        )
    return "" if value is None else str(value)


def _chat_finish_reason(reason: str | None) -> str:
    return {
        "STOP": "stop",
        "MAX_TOKENS": "length",
        "SAFETY": "content_filter",
    }.get(reason or "", "stop")

from .protocol import ChatMessage
from .model import ModelClient

_SUMMARY_PROMPT = """You are compacting a long conversation so older turns can be safely dropped from context.
Summarize the conversation below into a structured note with these sections:

## Goal
What the user is ultimately trying to accomplish.

## Progress
What has already been done or decided.

## Decisions
Any constraints, choices, or conclusions that must not be forgotten.

## Files and Code
Which files were created or modified, and the key functions, symbols, or code involved.

## Errors and Fixes
Errors that were hit and how they were fixed, so they are not repeated.

## Critical Context
Hard constraints or rules that must not be violated.

## Next Steps
What remains to be done, if anything.

Conversation:
{transcript}
"""


async def summarize_history(model_client: ModelClient, messages: list[ChatMessage]) -> str:
    """用固定的 Goal/Progress/Decisions/Next Steps 结构，让模型把一段历史总结成一条摘要。"""
    transcript = "\n".join(f"[{message.role}] {message.content}" for message in messages)
    prompt = _SUMMARY_PROMPT.format(transcript=transcript)
    completion = await model_client.acomplete([{"role": "user", "content": prompt}])
    return completion.text

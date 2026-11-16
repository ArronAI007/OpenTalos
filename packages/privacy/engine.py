"""Deterministic masking and reversible placeholder restoration."""

from __future__ import annotations

import copy
import json
import re
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any

from .store import PrivacyRule, PrivacyStore


class PrivacyBlockedError(RuntimeError):
    status_code = 451


class PrivacyUnavailableError(RuntimeError):
    status_code = 503


@dataclass
class MaskResult:
    text: str
    matches: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    placeholders: dict[str, str] = field(default_factory=dict)
    token_to_value: dict[str, str] = field(default_factory=dict)


@dataclass
class MaskedPayload:
    payload: dict[str, Any]
    matches: list[dict[str, Any]]
    warnings: list[dict[str, Any]]
    placeholders: dict[str, str]
    token_to_value: dict[str, str]


class PrivacyEngine:
    def __init__(
        self,
        store: PrivacyStore,
        *,
        fail_closed: bool = True,
        placeholder_ttl_seconds: int = 86400,
        rule_loader: Callable[[], list[PrivacyRule]] | None = None,
        settings_loader: Callable[[], dict[str, Any]] | None = None,
    ) -> None:
        self.store = store
        self.fail_closed = fail_closed
        self.placeholder_ttl_seconds = max(1, placeholder_ttl_seconds)
        self._rule_loader = rule_loader or store.list_rules
        self._settings_loader = settings_loader

    def mask_text(
        self,
        text: str,
        *,
        scope: str,
        request_id: str | None = None,
    ) -> MaskResult:
        try:
            settings = self._settings()
        except Exception as error:
            if self.fail_closed:
                raise PrivacyUnavailableError(
                    f"privacy settings unavailable: {error}"
                ) from error
            return MaskResult(text=text)
        if not settings["enabled"]:
            return MaskResult(text=text)
        try:
            rules = self._rule_loader()
            return self._mask_text_with_rules(
                text,
                scope=scope,
                request_id=request_id,
                rules=rules,
            )
        except PrivacyBlockedError:
            raise
        except Exception as error:
            if settings["fail_closed"]:
                raise PrivacyUnavailableError(
                    f"privacy masking unavailable: {error}"
                ) from error
            return MaskResult(text=text)

    def _mask_text_with_rules(
        self,
        text: str,
        *,
        scope: str,
        request_id: str | None,
        rules: list[PrivacyRule],
    ) -> MaskResult:
        result = MaskResult(text=text)
        for rule in rules:
            matches = list(re.finditer(rule.pattern, result.text, re.DOTALL))
            if not matches:
                continue
            if rule.action == "block":
                match_info = {
                    "rule_id": rule.id,
                    "title": rule.title,
                    "category": rule.category,
                    "action": rule.action,
                    "count": len(matches),
                }
                self.store.record_audit(
                    request_id=request_id,
                    scope=scope,
                    rule_id=rule.id,
                    category=rule.category,
                    action="block",
                    placeholder=None,
                    details={"count": len(matches)},
                )
                raise PrivacyBlockedError(
                    f"request blocked by privacy rule {rule.id} ({rule.title})"
                )
            values = [match.group(0) for match in matches]
            if rule.action == "warn":
                warning = {
                    "rule_id": rule.id,
                    "title": rule.title,
                    "category": rule.category,
                    "action": "warn",
                    "count": len(values),
                }
                result.warnings.append(warning)
                self.store.record_audit(
                    request_id=request_id,
                    scope=scope,
                    rule_id=rule.id,
                    category=rule.category,
                    action="warn",
                    placeholder=None,
                    details={"count": len(values)},
                )
                continue

            def replace(match: re.Match[str]) -> str:
                token = self.store.get_or_create_placeholder(
                    scope=scope,
                    rule_id=rule.id,
                    value=match.group(0),
                    ttl_seconds=self.placeholder_ttl_seconds,
                )
                result.placeholders[rule.id] = token
                result.token_to_value[token] = match.group(0)
                return token

            result.text = re.sub(rule.pattern, replace, result.text, flags=re.DOTALL)
            match_info = {
                "rule_id": rule.id,
                "title": rule.title,
                "category": rule.category,
                "action": "mask",
                "count": len(values),
                "placeholder": result.placeholders[rule.id],
            }
            result.matches.append(match_info)
            self.store.record_audit(
                request_id=request_id,
                scope=scope,
                rule_id=rule.id,
                category=rule.category,
                action="mask",
                placeholder=result.placeholders[rule.id],
                details={"count": len(values)},
            )
        return result

    def mask_payload(
        self,
        payload: dict[str, Any],
        *,
        scope: str,
        request_id: str | None = None,
    ) -> MaskedPayload:
        aggregate = MaskResult(text="")

        def visit(value: Any, key: str | None = None) -> Any:
            if isinstance(value, dict):
                return {
                    item_key: visit(item_value, item_key)
                    for item_key, item_value in value.items()
                }
            if isinstance(value, list):
                return [visit(item) for item in value]
            if isinstance(value, str) and key not in {
                "model",
                "model_id",
                "role",
                "type",
                "name",
            }:
                masked = self.mask_text(
                    value,
                    scope=scope,
                    request_id=request_id,
                )
                aggregate.matches.extend(masked.matches)
                aggregate.warnings.extend(masked.warnings)
                aggregate.placeholders.update(masked.placeholders)
                aggregate.token_to_value.update(masked.token_to_value)
                return masked.text
            return value

        return MaskedPayload(
            payload=visit(copy.deepcopy(payload)),
            matches=aggregate.matches,
            warnings=aggregate.warnings,
            placeholders=aggregate.placeholders,
            token_to_value=aggregate.token_to_value,
        )

    def restore_text(self, text: str, *, scope: str) -> str:
        mappings = self.store.mappings(scope)
        restored_tokens: list[str] = []
        for token in sorted(mappings, key=len, reverse=True):
            if token in text:
                text = text.replace(token, mappings[token])
                restored_tokens.append(token)
        self.store.mark_restored(scope, restored_tokens)
        return text

    def _settings(self) -> dict[str, Any]:
        if self._settings_loader is None:
            return {
                "enabled": True,
                "fail_closed": self.fail_closed,
                "placeholder_ttl_seconds": self.placeholder_ttl_seconds,
            }
        settings = self._settings_loader()
        self.fail_closed = bool(settings.get("fail_closed", self.fail_closed))
        self.placeholder_ttl_seconds = max(
            1,
            int(settings.get("placeholder_ttl_seconds", self.placeholder_ttl_seconds)),
        )
        return settings

    def restore_payload(self, value: Any, *, scope: str) -> Any:
        mappings = self.store.mappings(scope)

        def visit(item: Any) -> Any:
            if isinstance(item, dict):
                return {key: visit(child) for key, child in item.items()}
            if isinstance(item, list):
                return [visit(child) for child in item]
            if isinstance(item, str):
                restored = item
                for token in sorted(mappings, key=len, reverse=True):
                    restored = restored.replace(token, mappings[token])
                return restored
            return item

        restored = visit(copy.deepcopy(value))
        used = [token for token in mappings if _contains_token(value, token)]
        self.store.mark_restored(scope, used)
        return restored

    async def restore_sse(
        self,
        source: AsyncIterator[str],
        *,
        scope: str,
    ) -> AsyncIterator[str]:
        buffer = ""
        async for chunk in source:
            buffer += chunk
            while "\n\n" in buffer:
                block, buffer = buffer.split("\n\n", 1)
                yield self._restore_sse_block(block, scope=scope) + "\n\n"
        if buffer:
            yield self._restore_sse_block(buffer, scope=scope)

    def _restore_sse_block(self, block: str, *, scope: str) -> str:
        lines = block.splitlines()
        data_lines = [
            line[5:].strip()
            for line in lines
            if line.startswith("data:")
        ]
        if not data_lines:
            return block
        raw = "\n".join(data_lines)
        if raw == "[DONE]":
            return block
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            return block
        restored = self.restore_payload(event, scope=scope)
        event_lines = [line for line in lines if line.startswith("event:")]
        return "\n".join(
            [
                *event_lines,
                "data: "
                + json.dumps(restored, ensure_ascii=False, separators=(",", ":")),
            ]
        )


def _contains_token(value: Any, token: str) -> bool:
    if isinstance(value, dict):
        return any(_contains_token(child, token) for child in value.values())
    if isinstance(value, list):
        return any(_contains_token(child, token) for child in value)
    return isinstance(value, str) and token in value

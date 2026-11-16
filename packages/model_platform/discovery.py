"""Model discovery for OpenAI- and Anthropic-compatible provider accounts."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import httpx

from ai.model_catalog import get_model_capabilities
from model_platform.presets import get_preset


@dataclass(frozen=True)
class ModelDescriptor:
    model_id: str
    display_name: str
    protocol: str
    context_window: int | None
    supports_tools: bool
    supports_thinking: bool
    source: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ModelDiscovery:
    """Fetch model identifiers and enrich them with the local capability catalog."""

    async def discover(
        self,
        account: dict[str, Any],
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> list[ModelDescriptor]:
        backend = account["backend"]
        provider = account.get("provider") or backend
        if backend == "mock":
            return [
                ModelDescriptor(
                    model_id="mock-model",
                    display_name="Mock model",
                    protocol="mock",
                    context_window=None,
                    supports_tools=True,
                    supports_thinking=False,
                    source="built-in",
                )
            ]

        preset = get_preset(provider)
        base_url = account.get("base_url") or (
            preset.default_base_url if preset is not None else None
        )
        if backend == "gemini":
            gemini_base = (base_url or "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
            endpoint = f"{gemini_base}/models?key={account['api_key']}"
            headers = {}
            protocol = "gemini"
        elif backend == "anthropic":
            anthropic_base = (base_url or "https://api.anthropic.com").rstrip("/")
            endpoint = (
                f"{anthropic_base}/models"
                if anthropic_base.endswith("/v1")
                else f"{anthropic_base}/v1/models"
            )
            headers = {
                "x-api-key": account["api_key"],
                "anthropic-version": "2023-06-01",
            }
            protocol = "anthropic-messages"
        else:
            if not base_url:
                raise RuntimeError(f"provider {provider!r} requires a base_url")
            endpoint = f"{base_url.rstrip('/')}/models"
            headers = {"Authorization": f"Bearer {account['api_key']}"}
            protocol = "openai-chat"

        client_kwargs: dict[str, Any] = {
            "timeout": 20,
            "transport": transport,
            "trust_env": False,
        }
        if account.get("proxy_url"):
            client_kwargs["proxy"] = account["proxy_url"]
        async with httpx.AsyncClient(**client_kwargs) as client:
            response = await client.get(endpoint, headers=headers)
        if response.status_code >= 400:
            detail = response.text
            try:
                payload = response.json()
                detail = (
                    payload.get("error", {}).get("message")
                    or payload.get("error")
                    or detail
                )
            except ValueError:
                pass
            raise RuntimeError(f"model discovery failed ({response.status_code}): {detail}")

        try:
            payload = response.json()
        except ValueError as error:
            raise RuntimeError("model discovery returned invalid JSON") from error
        if backend == "gemini" and isinstance(payload, dict):
            entries = [
                {**model, "id": model.get("name", "")}
                for model in payload.get("models", [])
                if isinstance(model, dict)
            ]
        else:
            entries = payload.get("data", []) if isinstance(payload, dict) else payload
        if not isinstance(entries, list):
            raise RuntimeError("model discovery response has no model list")

        models: list[ModelDescriptor] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            model_id = entry.get("id") or entry.get("name")
            if not isinstance(model_id, str) or not model_id.strip():
                continue
            model_id = model_id.removeprefix("models/")
            capabilities = get_model_capabilities(model_id)
            models.append(
                ModelDescriptor(
                    model_id=model_id,
                    display_name=str(entry.get("display_name") or entry.get("name") or model_id),
                    protocol=protocol,
                    context_window=capabilities.context_window if capabilities else None,
                    supports_tools=capabilities.supports_tools if capabilities else True,
                    supports_thinking=capabilities.supports_thinking if capabilities else False,
                    source="provider",
                )
            )
        return models

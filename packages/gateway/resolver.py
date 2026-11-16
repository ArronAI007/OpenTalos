"""Resolve gateway model identifiers to enabled provider accounts."""

from __future__ import annotations

from dataclasses import dataclass

from model_platform.control_plane import ControlPlaneStore


class ModelResolutionError(ValueError):
    """Raised when a requested model cannot be mapped to one eligible account."""


@dataclass(frozen=True)
class ResolvedModel:
    account_id: str
    provider: str
    account_name: str
    backend: str
    base_url: str | None
    api_key: str
    proxy_url: str | None
    model_id: str
    protocol: str


class ModelResolver:
    def __init__(self, store: ControlPlaneStore) -> None:
        self.store = store

    def resolve(self, requested_model: str) -> ResolvedModel:
        requested = requested_model.strip()
        if not requested:
            raise ModelResolutionError("model is required")
        records = self.store.list_routable_models()
        if not records:
            raise ModelResolutionError("no enabled account has discovered models")

        for identity in (
            lambda row: f"{row['provider']}/{row['account_name']}/{row['model_id']}",
            lambda row: f"{row['provider']}/{row['model_id']}",
            lambda row: row["model_id"],
        ):
            matches = [row for row in records if identity(row) == requested]
            if len(matches) == 1:
                return _resolved(matches[0])
            if len(matches) > 1:
                if identity is not None and requested.startswith(f"{matches[0]['provider']}/"):
                    return _resolved(matches[0])
                raise ModelResolutionError(
                    f"model {requested!r} is ambiguous; use provider/account/model"
                )

        if "/" in requested:
            provider, model_id = requested.split("/", 1)
            provider_accounts = [row for row in records if row["provider"] == provider]
            if provider_accounts:
                chosen = provider_accounts[0]
                return ResolvedModel(
                    account_id=chosen["account_id"],
                    provider=chosen["provider"],
                    account_name=chosen["account_name"],
                    backend=chosen["backend"],
                    base_url=chosen["base_url"],
                    api_key=chosen["api_key"],
                    proxy_url=chosen["proxy_url"],
                    model_id=model_id,
                    protocol=chosen["protocol"],
                )

        raise ModelResolutionError(f"no enabled account can serve model {requested!r}")


def _resolved(row: dict) -> ResolvedModel:
    return ResolvedModel(
        account_id=row["account_id"],
        provider=row["provider"],
        account_name=row["account_name"],
        backend=row["backend"],
        base_url=row["base_url"],
        api_key=row["api_key"],
        proxy_url=row["proxy_url"],
        model_id=row["model_id"],
        protocol=row["protocol"],
    )

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
        candidates = self.candidates(requested_model)
        if len(candidates) > 1 and "/" not in requested_model:
            raise ModelResolutionError(
                f"model {requested_model!r} is ambiguous; use provider/account/model"
            )
        return candidates[0]

    def candidates(self, requested_model: str) -> list[ResolvedModel]:
        requested = requested_model.strip()
        if not requested:
            raise ModelResolutionError("model is required")
        records = self.store.list_routable_models()
        if not records:
            raise ModelResolutionError("no enabled account has discovered models")

        account_matches = [
            row
            for row in records
            if f"{row['provider']}/{row['account_name']}/{row['model_id']}" == requested
        ]
        if account_matches:
            return [_resolved(row) for row in account_matches]

        provider_matches = [
            row
            for row in records
            if f"{row['provider']}/{row['model_id']}" == requested
        ]
        if provider_matches:
            return [_resolved(row) for row in provider_matches]

        bare_matches = [row for row in records if row["model_id"] == requested]
        if bare_matches:
            return [_resolved(row) for row in bare_matches]

        if "/" in requested:
            provider, model_id = requested.split("/", 1)
            provider_accounts = [row for row in records if row["provider"] == provider]
            if provider_accounts:
                return [
                    ResolvedModel(
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
                    for chosen in provider_accounts
                ]

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

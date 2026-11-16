"""Explainable model routing groups, quota filtering, and session stickiness."""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Any, Callable

from gateway.request_log import GatewayRequestLog
from gateway.resolver import ModelResolutionError, ModelResolver, ResolvedModel
from model_platform.control_plane import ControlPlaneStore


class RoutingError(ValueError):
    """Raised when routing configuration or eligible candidates are invalid."""


@dataclass(frozen=True)
class WeightedCandidate:
    model: ResolvedModel
    target: str
    weight: float = 1.0


@dataclass(frozen=True)
class RoutingDecision:
    candidates: list[ResolvedModel]
    mode: str
    group_name: str | None
    trace: dict[str, Any]


class RoutingEngine:
    def __init__(
        self,
        store: ControlPlaneStore,
        *,
        request_log: GatewayRequestLog | None = None,
        now: Callable[[], datetime.datetime] | None = None,
    ) -> None:
        self.store = store
        self.request_log = request_log or GatewayRequestLog(store.path)
        self.resolver = ModelResolver(store)
        self.now = now or datetime.datetime.now

    def decide(
        self,
        requested_model: str,
        *,
        session_key: str | None = None,
    ) -> RoutingDecision:
        group_name: str | None = None
        mode = "order"
        if requested_model.startswith("group/"):
            group_name = requested_model.removeprefix("group/")
            group = self.store.get_routing_group(group_name)
            if group is None:
                raise RoutingError(f"group not found: {group_name}")
            weighted = self._expand_group(group, visited=())
            mode = group["mode"]
        else:
            try:
                weighted = [
                    WeightedCandidate(model, f"{model.account_id}:{model.model_id}")
                    for model in self.resolver.candidates(requested_model)
                ]
            except ModelResolutionError as error:
                raise RoutingError(str(error)) from error

        before = [
            {
                "account_id": candidate.model.account_id,
                "provider": candidate.model.provider,
                "account": candidate.model.account_name,
                "model": candidate.model.model_id,
            }
            for candidate in weighted
        ]
        eligible = self._filter_quota(weighted)
        if not eligible:
            raise RoutingError("no eligible account has remaining quota")
        ordered = self._order(eligible, mode=mode, group_name=group_name)

        scope = group_name or requested_model
        sticky = group_name is None or bool(
            self.store.get_routing_group(group_name)["sticky"]
        )
        binding_key = f"{scope}:{session_key}" if session_key else None
        if sticky and binding_key:
            bound = self.store.get_session_binding(binding_key)
            ordered.sort(key=lambda candidate: candidate.target != bound)

        selected = ordered[0]
        if binding_key:
            self.store.set_session_binding(binding_key, selected.target)

        trace = {
            "requested_model": requested_model,
            "group": group_name,
            "mode": mode,
            "session_key": session_key,
            "candidates": before,
            "eligible": [candidate.target for candidate in eligible],
            "selected": selected.target,
            "filtered_quota": max(0, len(weighted) - len(eligible)),
        }
        return RoutingDecision(
            candidates=[candidate.model for candidate in ordered],
            mode=mode,
            group_name=group_name,
            trace=trace,
        )

    def _expand_group(
        self,
        group: dict[str, Any],
        *,
        visited: tuple[str, ...],
    ) -> list[WeightedCandidate]:
        name = group["name"]
        if name in visited:
            raise RoutingError(f"routing group cycle: {' -> '.join((*visited, name))}")
        path = (*visited, name)
        candidates: list[WeightedCandidate] = []
        for member in group["members"]:
            target = member["target"]
            weight = float(member.get("weight", 1))
            if target.startswith("group/"):
                nested_name = target.removeprefix("group/")
                nested = self.store.get_routing_group(nested_name)
                if nested is None:
                    raise RoutingError(f"group not found: {nested_name}")
                nested_candidates = self._expand_group(nested, visited=path)
                candidates.extend(
                    WeightedCandidate(
                        candidate.model,
                        candidate.target,
                        weight * candidate.weight,
                    )
                    for candidate in nested_candidates
                )
                continue
            try:
                models = self.resolver.candidates(target)
            except ModelResolutionError as error:
                raise RoutingError(str(error)) from error
            candidates.extend(
                WeightedCandidate(
                    model,
                    f"{model.account_id}:{model.model_id}",
                    weight,
                )
                for model in models
            )
        deduped: dict[str, WeightedCandidate] = {}
        for candidate in candidates:
            deduped.setdefault(candidate.target, candidate)
        return list(deduped.values())

    def _filter_quota(
        self,
        candidates: list[WeightedCandidate],
    ) -> list[WeightedCandidate]:
        snapshots = self.store.latest_quota_snapshots()
        by_account: dict[str, list[dict[str, Any]]] = {}
        for snapshot in snapshots:
            by_account.setdefault(snapshot["account_id"], []).append(snapshot)
        now = self.now()
        eligible: list[WeightedCandidate] = []
        for candidate in candidates:
            account_snapshots = by_account.get(candidate.model.account_id, [])
            if any(_quota_exhausted(snapshot, now) for snapshot in account_snapshots):
                continue
            eligible.append(candidate)
        return eligible

    def _order(
        self,
        candidates: list[WeightedCandidate],
        *,
        mode: str,
        group_name: str | None,
    ) -> list[WeightedCandidate]:
        ordered = list(candidates)
        if mode == "rotate":
            counter = self.store.next_routing_counter(f"group:{group_name or 'model'}")
            shift = (counter - 1) % len(ordered)
            ordered = ordered[shift:] + ordered[:shift]
        elif mode == "usage":
            usage = self.request_log.usage_by_account()
            ordered.sort(
                key=lambda item: usage.get(
                    f"{item.model.provider}/{item.model.account_name}",
                    0,
                )
            )
        elif mode in {"smart", "pace"}:
            quotas = self._account_quota(ordered)
            if mode == "smart":
                ordered.sort(key=lambda item: _smart_key(quotas.get(item.model.account_id)))
            else:
                ordered.sort(
                    key=lambda item: _pace_key(
                        quotas.get(item.model.account_id),
                        self.now(),
                    ),
                    reverse=True,
                )
        elif mode == "weight":
            counter = self.store.next_routing_counter(f"group:{group_name or 'model'}")
            weighted_sequence = [
                item for item in ordered for _ in range(max(1, int(item.weight)))
            ]
            selected = weighted_sequence[(counter - 1) % len(weighted_sequence)]
            ordered = [selected] + [item for item in ordered if item is not selected]
        return ordered

    def _account_quota(
        self,
        candidates: list[WeightedCandidate],
    ) -> dict[str, dict[str, Any]]:
        account_ids = {candidate.model.account_id for candidate in candidates}
        result: dict[str, dict[str, Any]] = {}
        for snapshot in self.store.latest_quota_snapshots():
            if snapshot["account_id"] not in account_ids:
                continue
            current = result.get(snapshot["account_id"])
            if current is None or _reset_at(snapshot) < _reset_at(current):
                result[snapshot["account_id"]] = snapshot
        return result


def _quota_exhausted(snapshot: dict[str, Any], now: datetime.datetime) -> bool:
    reset = _reset_at(snapshot)
    return float(snapshot["remaining"]) <= 0 and (reset is None or reset > now)


def _reset_at(snapshot: dict[str, Any] | None) -> datetime.datetime | None:
    if not snapshot or not snapshot.get("reset_at"):
        return None
    try:
        return datetime.datetime.fromisoformat(str(snapshot["reset_at"]).replace("Z", "+00:00")).replace(
            tzinfo=None
        )
    except ValueError:
        return None


def _smart_key(snapshot: dict[str, Any] | None) -> tuple[int, datetime.datetime]:
    reset = _reset_at(snapshot)
    return (0, reset) if reset is not None else (1, datetime.datetime.max)


def _pace_key(
    snapshot: dict[str, Any] | None,
    now: datetime.datetime,
) -> float:
    if snapshot is None:
        return 0
    limit = max(float(snapshot["limit_value"]), 1)
    remaining = max(float(snapshot["remaining"]), 0) / limit
    reset = _reset_at(snapshot)
    hours = max(((reset - now).total_seconds() / 3600) if reset else 168, 1)
    return remaining / hours

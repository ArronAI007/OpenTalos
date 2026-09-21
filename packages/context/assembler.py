import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from core.chat_message import ChatMessage

from .tokens import TokenBudget

_RECENCY_HALF_LIFE_SECONDS = 3600.0
_RELEVANCE_WEIGHT = 0.7
_RECENCY_WEIGHT = 0.3


@dataclass
class ContextSlice:
    content: str
    kind: str
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)
    relevance: float = 0.0
    token_count: int = 0


@dataclass
class AssemblyConfig:
    max_tokens: int = 8000
    reserve_ratio: float = 0.15
    min_relevance: float = 0.3
    enable_mmr: bool = True
    mmr_lambda: float = 0.7  # 1.0 = 只看相关性，0.0 = 只看多样性
    enable_compression: bool = True

    @property
    def budget_tokens(self) -> int:
        return int(self.max_tokens * (1 - self.reserve_ratio))


class ContextAssembler:
    """Gather -> Select -> Structure -> Compress 上下文组装流水线。

    Select 阶段用相关性 + 新近性打分排序，enable_mmr 时改用最大边际相关性
    （MMR）在候选间做多样性取舍，避免选出的材料互相重复。
    """

    def __init__(self, config: AssemblyConfig | None = None, token_budget: TokenBudget | None = None) -> None:
        self.config = config or AssemblyConfig()
        self._tokens = token_budget or TokenBudget()

    def assemble(
        self,
        user_query: str,
        transcript: list[ChatMessage] | None = None,
        system_instructions: str | None = None,
        extra_slices: list[ContextSlice] | None = None,
    ) -> str:
        slices = self._collect(user_query, transcript or [], system_instructions, extra_slices or [])
        selected = self._rank(slices)
        layout = self._layout(selected, user_query)
        return self._condense(layout)

    def _collect(
        self,
        user_query: str,
        transcript: list[ChatMessage],
        system_instructions: str | None,
        extra_slices: list[ContextSlice],
    ) -> list[ContextSlice]:
        slices: list[ContextSlice] = []

        if system_instructions:
            slices.append(self._make_slice(system_instructions, kind="instructions"))

        if transcript:
            recent = transcript[-10:]
            text = "\n".join(message.as_text() for message in recent)
            slices.append(self._make_slice(text, kind="history", metadata={"count": len(recent)}))

        for extra in extra_slices:
            extra.token_count = extra.token_count or self._tokens.estimate_text(extra.content)
        slices.extend(extra_slices)

        query_terms = set(user_query.lower().split())
        for slice_ in slices:
            slice_.relevance = self._relevance(slice_.content, query_terms)
        return slices

    def _make_slice(self, content: str, *, kind: str, metadata: dict[str, Any] | None = None) -> ContextSlice:
        return ContextSlice(
            content=content,
            kind=kind,
            metadata=metadata or {},
            token_count=self._tokens.estimate_text(content),
        )

    def _rank(self, slices: list[ContextSlice]) -> list[ContextSlice]:
        pinned = [s for s in slices if s.kind == "instructions"]
        candidates = [s for s in slices if s.kind != "instructions" and s.relevance >= self.config.min_relevance]

        scores = {id(s): _RELEVANCE_WEIGHT * s.relevance + _RECENCY_WEIGHT * self._recency(s.timestamp) for s in candidates}
        ordered = (
            self._select_diverse(candidates, scores)
            if self.config.enable_mmr
            else sorted(candidates, key=lambda s: scores[id(s)], reverse=True)
        )

        budget = self.config.budget_tokens
        selected: list[ContextSlice] = []
        used = 0
        for slice_ in pinned + ordered:
            if used + slice_.token_count > budget:
                continue
            selected.append(slice_)
            used += slice_.token_count
        return selected

    def _select_diverse(self, candidates: list[ContextSlice], scores: dict[int, float]) -> list[ContextSlice]:
        """贪心 MMR：每步在“分高”和“与已选内容不同”之间取平衡。"""
        remaining = sorted(candidates, key=lambda s: scores[id(s)], reverse=True)
        chosen: list[ContextSlice] = []
        lam = self.config.mmr_lambda

        while remaining:
            if not chosen:
                chosen.append(remaining.pop(0))
                continue
            best_index, best_value = 0, float("-inf")
            for index, candidate in enumerate(remaining):
                max_similarity = max(self._similarity(candidate.content, picked.content) for picked in chosen)
                value = lam * scores[id(candidate)] - (1 - lam) * max_similarity
                if value > best_value:
                    best_index, best_value = index, value
            chosen.append(remaining.pop(best_index))
        return chosen

    @staticmethod
    def _relevance(content: str, query_terms: set[str]) -> float:
        if not query_terms:
            return 0.0
        content_terms = set(content.lower().split())
        return len(query_terms & content_terms) / len(query_terms)

    @staticmethod
    def _recency(timestamp: datetime) -> float:
        elapsed = max((datetime.now() - timestamp).total_seconds(), 0.0)
        return math.exp(-elapsed / _RECENCY_HALF_LIFE_SECONDS)

    @staticmethod
    def _similarity(a: str, b: str) -> float:
        terms_a, terms_b = set(a.lower().split()), set(b.lower().split())
        if not terms_a or not terms_b:
            return 0.0
        return len(terms_a & terms_b) / len(terms_a | terms_b)

    def _layout(self, selected: list[ContextSlice], user_query: str) -> str:
        sections: list[str] = []

        instructions = [s for s in selected if s.kind == "instructions"]
        if instructions:
            sections.append("[Role & Policies]\n" + "\n".join(s.content for s in instructions))

        sections.append(f"[Task]\n{user_query}")

        evidence = [s for s in selected if s.kind in {"evidence", "tool_result", "retrieval"}]
        if evidence:
            sections.append("[Evidence]\n" + "\n\n".join(s.content for s in evidence))

        history = [s for s in selected if s.kind == "history"]
        if history:
            sections.append("[Context]\n" + "\n".join(s.content for s in history))

        sections.append(
            "[Output]\n"
            "1. Conclusion\n"
            "2. Supporting evidence\n"
            "3. Risks / assumptions (if any)\n"
            "4. Suggested next step (if applicable)"
        )
        return "\n\n".join(sections)

    def _condense(self, context: str) -> str:
        if not self.config.enable_compression:
            return context

        budget = self.config.budget_tokens
        if self._tokens.estimate_text(context) <= budget:
            return context

        kept: list[str] = []
        used = 0
        for line in context.split("\n"):
            line_tokens = self._tokens.estimate_text(line)
            if used + line_tokens > budget:
                break
            kept.append(line)
            used += line_tokens
        return "\n".join(kept)

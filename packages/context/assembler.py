import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .message import MessageLike
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

    Structure 阶段把入选的 slice 按 kind 分到六个区块：
    instructions（固定纳入，不参与排序/预算竞争之外的其它 slice） -> [Role & Policies]，
    state -> [State]，
    evidence/memory/knowledge/retrieval/tool_result -> [Evidence]，
    history -> [Context]。
    """

    def __init__(self, config: AssemblyConfig | None = None, token_budget: TokenBudget | None = None) -> None:
        self.config = config or AssemblyConfig()
        self._tokens = token_budget or TokenBudget()

    def assemble(
        self,
        user_query: str,
        transcript: list[MessageLike] | None = None,
        system_instructions: str | None = None,
        extra_slices: list[ContextSlice] | None = None,
    ) -> str:
        slices = self._collect(user_query, transcript or [], system_instructions, extra_slices or [])
        selected = self._rank(slices)
        layout = self._layout(selected, user_query)
        return self._condense(layout)

    def select_recent_turns(self, messages: list[MessageLike], budget_tokens: int) -> list[MessageLike]:
        """按"轮次"（一条 role=="user" 的消息开始，到下一条 user 消息之前的全部内容）为最小
        粒度做筛选——按时间倒序保留最近几轮直到装满 token 预算，整轮保留或整轮丢弃，从不
        拆开单轮内部（避免把 tool_calls 和它的工具结果拆散，那样会让 messages 列表对
        OpenAI/Anthropic 风格的 API 来说是非法请求）。不做关键词相关性打分/MMR 多样性排序
        ——和 assemble() 那条路径是平行的两套逻辑，互不影响。极端情况（单轮本身就超预算）
        至少保留最新一轮，不返回空列表（除非输入本来就是空的）。
        """
        if not messages:
            return []

        turn_starts = [i for i, m in enumerate(messages) if m.role == "user"]
        if not turn_starts or turn_starts[0] != 0:
            turn_starts = [0, *turn_starts]
        bounds = list(zip(turn_starts, [*turn_starts[1:], len(messages)]))
        turns = [messages[start:end] for start, end in bounds]

        kept: list[list[MessageLike]] = []
        used = 0
        for turn in reversed(turns):
            turn_tokens = self._tokens.estimate_messages(turn)
            if used + turn_tokens > budget_tokens and kept:
                break
            kept.append(turn)
            used += turn_tokens
        kept.reverse()
        return [message for turn in kept for message in turn]

    def _collect(
        self,
        user_query: str,
        transcript: list[MessageLike],
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

        state = [s for s in selected if s.kind == "state"]
        if state:
            sections.append("[State]\n" + "\n".join(s.content for s in state))

        evidence = [s for s in selected if s.kind in {"evidence", "memory", "knowledge", "retrieval", "tool_result"}]
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

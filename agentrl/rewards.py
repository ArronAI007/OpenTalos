"""GRPO 奖励函数——不依赖模型，纯文本打分。trl.GRPOTrainer 按 reward_funcs 列表依次调用，
每个函数签名统一为 (completions, ground_truth, **kwargs) -> list[float]，多个函数的得分会被加总。
"""
import re

_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")
_MAX_PENALTY_FREE_LENGTH = 80  # 超过这个字符数开始扣分——demo 数据集答案都很短，这个阈值足够宽松


def extract_numeric_answer(text: str) -> str | None:
    """取文本里最后一个数字作为模型给出的最终答案——模型推理过程可能提到中间数字，
    最后一个通常才是结论。"""
    matches = _NUMBER_RE.findall(text)
    return matches[-1] if matches else None


def accuracy_reward(*, completions: list[str], ground_truth: list[str], **_kwargs: object) -> list[float]:
    rewards = []
    for completion, expected in zip(completions, ground_truth):
        extracted = extract_numeric_answer(completion)
        rewards.append(1.0 if extracted is not None and float(extracted) == float(expected) else 0.0)
    return rewards


def length_penalty_reward(*, completions: list[str], **_kwargs: object) -> list[float]:
    rewards = []
    for completion in completions:
        overflow = max(0, len(completion) - _MAX_PENALTY_FREE_LENGTH)
        rewards.append(-overflow / _MAX_PENALTY_FREE_LENGTH)
    return rewards

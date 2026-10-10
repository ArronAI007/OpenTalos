"""模型调用成本估算：按 token 用量 × 价目表算美元。

刻意不内置默认价目表——价格会变，硬编码的过期价格比"没有成本"更糟（会误导预算判断）。
价目表由环境变量 MODEL_PRICES 提供（JSON，单位：美元 / 100 万 token）：
    MODEL_PRICES={"gpt-4o": {"input": 2.5, "output": 10}, "claude-sonnet-4": {"input": 3, "output": 15}}
未配置、JSON 非法、或模型不在表里时返回 None（调用方据此不展示成本，而不是展示假的 0）。
"""

import json
import os


def load_prices() -> dict[str, dict[str, float]]:
    raw = os.environ.get("MODEL_PRICES")
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    prices: dict[str, dict[str, float]] = {}
    for model, entry in data.items():
        if not isinstance(entry, dict):
            continue
        try:
            prices[str(model)] = {"input": float(entry["input"]), "output": float(entry["output"])}
        except (KeyError, TypeError, ValueError):
            continue
    return prices


def estimate_cost(
    model_id: str | None,
    token_usage: dict[str, int],
    prices: dict[str, dict[str, float]] | None = None,
) -> float | None:
    """返回该次调用的美元成本；模型未知/无价目时返回 None。"""
    table = load_prices() if prices is None else prices
    if not model_id or model_id not in table:
        return None
    price = table[model_id]
    prompt = token_usage.get("prompt_tokens", 0)
    completion = token_usage.get("completion_tokens", 0)
    return (prompt / 1_000_000) * price["input"] + (completion / 1_000_000) * price["output"]

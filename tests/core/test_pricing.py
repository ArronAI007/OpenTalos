from core.pricing import estimate_cost, load_prices


def test_load_prices_parses_the_env_json(monkeypatch):
    monkeypatch.setenv("MODEL_PRICES", '{"gpt-4o": {"input": 2.5, "output": 10}}')
    assert load_prices() == {"gpt-4o": {"input": 2.5, "output": 10.0}}


def test_load_prices_ignores_invalid_json_and_entries(monkeypatch):
    monkeypatch.setenv("MODEL_PRICES", "not json")
    assert load_prices() == {}
    monkeypatch.setenv("MODEL_PRICES", '{"x": {"input": 1}}')  # 缺 output
    assert load_prices() == {}


def test_estimate_cost_computes_dollars_from_tokens():
    prices = {"m": {"input": 2.0, "output": 10.0}}
    cost = estimate_cost("m", {"prompt_tokens": 1_000_000, "completion_tokens": 500_000}, prices)
    assert cost == 7.0


def test_estimate_cost_is_none_for_unknown_model_or_no_table():
    assert estimate_cost("m", {"prompt_tokens": 1}, {}) is None
    assert estimate_cost(None, {"prompt_tokens": 1}, {"m": {"input": 1, "output": 1}}) is None

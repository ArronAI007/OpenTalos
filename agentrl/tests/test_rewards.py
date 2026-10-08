from rewards import accuracy_reward, extract_numeric_answer, length_penalty_reward


def test_extract_numeric_answer_finds_trailing_integer() -> None:
    assert extract_numeric_answer("计算过程略，答案是8") == "8"


def test_extract_numeric_answer_finds_decimal() -> None:
    assert extract_numeric_answer("结果约为 3.5") == "3.5"


def test_extract_numeric_answer_returns_none_when_no_number() -> None:
    assert extract_numeric_answer("我不知道") is None


def test_accuracy_reward_scores_exact_matches() -> None:
    completions = ["答案是8", "答案是7"]
    ground_truth = ["8", "8"]
    assert accuracy_reward(completions=completions, ground_truth=ground_truth) == [1.0, 0.0]


def test_accuracy_reward_scores_zero_when_unparseable() -> None:
    assert accuracy_reward(completions=["不知道"], ground_truth=["8"]) == [0.0]


def test_length_penalty_reward_favors_shorter_completions() -> None:
    short_reward, long_reward = length_penalty_reward(
        completions=["答案是8", "答案是8" + "，" * 200]
    )
    assert short_reward > long_reward

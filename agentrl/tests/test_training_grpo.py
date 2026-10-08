from tests.helpers import build_tiny_model_and_tokenizer
from training import run_grpo, run_sft


def test_run_grpo_reports_reward_per_step_after_sft() -> None:
    model, tokenizer = build_tiny_model_and_tokenizer()
    examples = [
        {"question": "1+1等于几？", "answer": "2", "solution": "1 + 1 = 2"},
        {"question": "2+2等于几？", "answer": "4", "solution": "2 + 2 = 4"},
    ]
    sft_model = run_sft(model, tokenizer, examples, steps=1, on_step=lambda *_: None)

    rewards: list[float] = []
    run_grpo(sft_model, tokenizer, examples, steps=2, on_step=lambda step, reward: rewards.append(reward))

    assert len(rewards) == 2
    assert all(isinstance(reward, float) for reward in rewards)

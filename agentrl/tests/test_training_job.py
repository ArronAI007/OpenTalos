from tests.helpers import build_tiny_model_and_tokenizer
from training import run_training_job


def test_run_training_job_reports_metrics_and_returns_comparisons() -> None:
    config = {"sft_samples": 2, "sft_steps": 1, "grpo_samples": 2, "grpo_steps": 1}
    events: list[tuple[str, int, float]] = []

    result = run_training_job(
        config,
        on_metric=lambda phase, step, value: events.append((phase, step, value)),
        model_loader=build_tiny_model_and_tokenizer,
    )

    assert any(phase == "sft_loss" for phase, _, _ in events)
    assert any(phase == "grpo_reward" for phase, _, _ in events)
    assert len(result["comparisons"]) >= 1
    for item in result["comparisons"]:
        assert set(item) == {"question", "before", "after", "expected"}

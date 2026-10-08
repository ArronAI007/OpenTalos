from peft import PeftModel

from tests.helpers import build_tiny_model_and_tokenizer
from training import run_sft


def test_run_sft_reports_loss_per_step_and_returns_a_peft_model() -> None:
    model, tokenizer = build_tiny_model_and_tokenizer()
    examples = [
        {"question": "1+1等于几？", "answer": "2", "solution": "1 + 1 = 2"},
        {"question": "2+2等于几？", "answer": "4", "solution": "2 + 2 = 4"},
    ]
    losses: list[float] = []

    result = run_sft(model, tokenizer, examples, steps=2, on_step=lambda step, loss: losses.append(loss))

    assert isinstance(result, PeftModel)
    assert len(losses) == 2
    assert all(isinstance(loss, float) for loss in losses)

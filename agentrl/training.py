"""SFT + GRPO 训练核心逻辑。model/tokenizer 由调用方传入（依赖注入）——生产代码路径用
load_base_model_and_tokenizer() 加载真实 Qwen3-0.6B，测试路径用 tests/helpers.py 的极小模型，
两边共用同一套训练函数，不是两套代码。"""
import copy
from collections.abc import Callable

import torch
from datasets import Dataset
from peft import LoraConfig, PeftModel, TaskType, get_peft_model
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    PreTrainedModel,
    PreTrainedTokenizerBase,
    Trainer,
    TrainerCallback,
    TrainingArguments,
)
from trl import GRPOConfig, GRPOTrainer

from dataset import load_problems
from rewards import accuracy_reward, length_penalty_reward

_BASE_MODEL_NAME = "Qwen/Qwen3-0.6B"
_LORA_TARGET_MODULES = ["q_proj", "v_proj"]


def load_base_model_and_tokenizer() -> tuple[PreTrainedModel, PreTrainedTokenizerBase]:
    """生产代码路径——加载真实模型，首次调用触发 HuggingFace 下载。"""
    tokenizer = AutoTokenizer.from_pretrained(_BASE_MODEL_NAME)
    model = AutoModelForCausalLM.from_pretrained(_BASE_MODEL_NAME)
    return model, tokenizer


def _format_sft_example(example: dict[str, str]) -> str:
    return f"问题：{example['question']}\n解答：{example['solution']}"


class _StepReporter(TrainerCallback):
    def __init__(self, on_step: Callable[[int, float], None]) -> None:
        self._on_step = on_step

    def on_log(self, args, state, control, logs=None, **kwargs):  # noqa: ANN001 - transformers 回调签名
        if logs and "loss" in logs:
            self._on_step(state.global_step, float(logs["loss"]))


def run_sft(
    model: PreTrainedModel,
    tokenizer: PreTrainedTokenizerBase,
    examples: list[dict[str, str]],
    *,
    steps: int,
    on_step: Callable[[int, float], None],
) -> PeftModel:
    peft_model = get_peft_model(
        model, LoraConfig(r=8, lora_alpha=8, target_modules=_LORA_TARGET_MODULES, task_type=TaskType.CAUSAL_LM)
    )

    texts = [_format_sft_example(example) for example in examples]
    encodings = tokenizer(texts, padding=True, truncation=True, max_length=128, return_tensors="pt")

    class _SftDataset:
        def __len__(self) -> int:
            return len(texts)

        def __getitem__(self, idx: int) -> dict:
            return {
                "input_ids": encodings["input_ids"][idx],
                "attention_mask": encodings["attention_mask"][idx],
                "labels": encodings["input_ids"][idx],
            }

    args = TrainingArguments(
        output_dir="/tmp/agentrl-sft",  # 中间 checkpoint 不需要持久化，训练结束就不再需要
        max_steps=steps,
        per_device_train_batch_size=min(2, len(examples)),
        learning_rate=1e-4,
        logging_steps=1,
        report_to=[],
        save_strategy="no",
    )
    trainer = Trainer(
        model=peft_model, args=args, train_dataset=_SftDataset(), callbacks=[_StepReporter(on_step)]
    )
    trainer.train()
    return peft_model


def run_grpo(
    model: PreTrainedModel,
    tokenizer: PreTrainedTokenizerBase,
    examples: list[dict[str, str]],
    *,
    steps: int,
    on_step: Callable[[int, float], None],
) -> PreTrainedModel:
    dataset = Dataset.from_list(
        [{"prompt": f"问题：{ex['question']}\n解答：", "ground_truth": ex["answer"]} for ex in examples]
    )

    config = GRPOConfig(
        output_dir="/tmp/agentrl-grpo",
        max_steps=steps,
        num_generations=2,
        max_completion_length=32,
        per_device_train_batch_size=2,
        learning_rate=1e-5,
        logging_steps=1,
        report_to=[],
        save_strategy="no",
    )

    def _accuracy(completions, ground_truth, **kwargs):  # noqa: ANN001 - trl 回调签名
        return accuracy_reward(completions=completions, ground_truth=ground_truth)

    def _length(completions, **kwargs):  # noqa: ANN001
        return length_penalty_reward(completions=completions)

    trainer = GRPOTrainer(
        model=model,
        reward_funcs=[_accuracy, _length],
        args=config,
        train_dataset=dataset,
        processing_class=tokenizer,
    )

    class _RewardReporter(TrainerCallback):
        def on_log(self, args, state, control, logs=None, **kwargs):  # noqa: ANN001
            if logs and "reward" in logs:
                on_step(state.global_step, float(logs["reward"]))

    trainer.add_callback(_RewardReporter())
    trainer.train()
    return model


_NUM_COMPARISON_SAMPLES = 3


def _generate(model: PreTrainedModel, tokenizer: PreTrainedTokenizerBase, question: str) -> str:
    # trainer.train() 结束后模型还留在 train 模式（dropout 仍激活）——不切回 eval 模式会让
    # 哪怕是贪心解码（do_sample=False）也因为每次前向的 dropout 噪声而生成退化的重复文本。
    model.eval()
    prompt = f"问题：{question}\n解答："
    inputs = tokenizer(prompt, return_tensors="pt")
    with torch.no_grad():
        output_ids = model.generate(**inputs, max_new_tokens=64, do_sample=False)
    return tokenizer.decode(output_ids[0][inputs["input_ids"].shape[1] :], skip_special_tokens=True)


def run_training_job(
    config: dict[str, int],
    *,
    on_metric: Callable[[str, int, float], None],
    model_loader: Callable[[], tuple[PreTrainedModel, PreTrainedTokenizerBase]] = load_base_model_and_tokenizer,
) -> dict:
    """SFT -> GRPO -> 训练前后样例对比，整个过程是阻塞的同步调用（调用方负责丢进后台线程）。"""
    model, tokenizer = model_loader()
    base_model_for_comparison = copy.deepcopy(model)

    sft_examples = load_problems(config["sft_samples"])
    sft_model = run_sft(
        model, tokenizer, sft_examples, steps=config["sft_steps"],
        on_step=lambda step, loss: on_metric("sft_loss", step, loss),
    )

    grpo_examples = load_problems(config["grpo_samples"])
    trained_model = run_grpo(
        sft_model, tokenizer, grpo_examples, steps=config["grpo_steps"],
        on_step=lambda step, reward: on_metric("grpo_reward", step, reward),
    )

    comparison_pool = load_problems(min(_NUM_COMPARISON_SAMPLES, len(sft_examples) + len(grpo_examples)))
    comparisons = [
        {
            "question": item["question"],
            "before": _generate(base_model_for_comparison, tokenizer, item["question"]),
            "after": _generate(trained_model, tokenizer, item["question"]),
            "expected": item["answer"],
        }
        for item in comparison_pool
    ]
    return {"comparisons": comparisons}

"""SFT + GRPO 训练核心逻辑。model/tokenizer 由调用方传入（依赖注入）——生产代码路径用
load_base_model_and_tokenizer() 加载真实 Qwen3-0.6B，测试路径用 tests/helpers.py 的极小模型，
两边共用同一套训练函数，不是两套代码。"""
from collections.abc import Callable

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

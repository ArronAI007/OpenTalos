"""测试专用的真实-但-极小模型构造——不是 mock，是真的 Qwen3 架构、真的 tokenizer，只是
hidden_size/层数小到几秒内能跑完真实的 SFT/GRPO 训练循环。真实的 Qwen/Qwen3-0.6B 只在生产
代码路径（training.load_base_model_and_tokenizer）里出现，测试永远不碰它。"""
from transformers import AutoModelForCausalLM, AutoTokenizer, PreTrainedModel, PreTrainedTokenizerBase, Qwen3Config

_TOKENIZER_NAME = "Qwen/Qwen3-0.6B"


def build_tiny_model_and_tokenizer() -> tuple[PreTrainedModel, PreTrainedTokenizerBase]:
    tokenizer = AutoTokenizer.from_pretrained(_TOKENIZER_NAME)
    config = Qwen3Config(
        vocab_size=tokenizer.vocab_size + len(tokenizer.get_added_vocab()),
        hidden_size=32,
        num_hidden_layers=2,
        num_attention_heads=4,
        num_key_value_heads=2,
        head_dim=8,
        intermediate_size=64,
    )
    model = AutoModelForCausalLM.from_config(config)
    return model, tokenizer

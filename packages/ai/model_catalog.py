"""小型、手工维护的模型能力目录：上下文窗口/是否支持工具调用/是否支持 thinking。

和 pricing.py 刻意保持独立——不含任何价格/成本数据（FR-007）；两个模块互不 import。数据来源
是维护者手工填写，不从任何外部数据源自动同步；查不到的模型返回 None，不编造数值（FR-006），
这点和 pricing.py"查不到就是 None、不猜测"的哲学一致。

下面这张表里的 context_window 数字来自各家官方文档公开记录的规格，但没有在本次改动时逐一对照
实时文档重新核实——如果某个数字后续被发现不准确，请直接更新这里，不需要走额外流程（这正是"手
工维护"这个取舍本身包含的局限，见 spec.md 的 Edge Cases）。
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class ModelCapabilities:
    context_window: int
    supports_tools: bool
    supports_thinking: bool


_CATALOG: dict[str, ModelCapabilities] = {
    "claude-sonnet-5": ModelCapabilities(context_window=200_000, supports_tools=True, supports_thinking=True),
    "claude-opus-5": ModelCapabilities(context_window=200_000, supports_tools=True, supports_thinking=True),
    "gpt-4o": ModelCapabilities(context_window=128_000, supports_tools=True, supports_thinking=False),
    "deepseek-chat": ModelCapabilities(context_window=64_000, supports_tools=True, supports_thinking=True),
    "moonshot-v1-128k": ModelCapabilities(context_window=128_000, supports_tools=True, supports_thinking=False),
}


def get_model_capabilities(model_name: str) -> ModelCapabilities | None:
    return _CATALOG.get(model_name)


# 和改动前 apps/api/main.py 硬编码的 compaction_token_limit 默认值完全一致——模型未登记进目录
# 时回退到这个数字，保证现状部署的默认压缩行为不因为这次改动而变化（FR-010）。
_LEGACY_DEFAULT_COMPACTION_TOKEN_LIMIT = 16000


def default_compaction_token_limit(model_name: str) -> int:
    """永远返回一个可用的 int，不是 Optional。已知模型用上下文窗口的一半（给摘要本身、新一轮
    工具调用、模型输出留出余量）；未知模型回退到改动前的硬编码默认值。"""
    capabilities = get_model_capabilities(model_name)
    if capabilities is None:
        return _LEGACY_DEFAULT_COMPACTION_TOKEN_LIMIT
    return int(capabilities.context_window * 0.5)

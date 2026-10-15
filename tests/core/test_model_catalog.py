"""模型能力目录的单测：纯数据查询，不含任何价格数据，不 import pricing.py。"""
import ast
from pathlib import Path

from core.model_catalog import (
    _LEGACY_DEFAULT_COMPACTION_TOKEN_LIMIT,
    ModelCapabilities,
    default_compaction_token_limit,
    get_model_capabilities,
)


class TestGetModelCapabilities:
    def test_registered_model_returns_complete_data(self) -> None:
        capabilities = get_model_capabilities("claude-sonnet-5")
        assert capabilities is not None
        assert isinstance(capabilities.context_window, int) and capabilities.context_window > 0
        assert isinstance(capabilities.supports_tools, bool)
        assert isinstance(capabilities.supports_thinking, bool)

    def test_unregistered_model_returns_none(self) -> None:
        assert get_model_capabilities("some-unregistered-model") is None


class TestDefaultCompactionTokenLimit:
    def test_known_model_uses_half_the_context_window(self) -> None:
        capabilities = get_model_capabilities("claude-sonnet-5")
        assert default_compaction_token_limit("claude-sonnet-5") == int(capabilities.context_window * 0.5)

    def test_unknown_model_falls_back_to_the_legacy_default(self) -> None:
        assert default_compaction_token_limit("some-unregistered-model") == 16000
        assert _LEGACY_DEFAULT_COMPACTION_TOKEN_LIMIT == 16000


class TestNoPriceData:
    def test_model_capabilities_has_no_price_fields(self) -> None:
        field_names = {f.name for f in ModelCapabilities.__dataclass_fields__.values()}
        assert field_names == {"context_window", "supports_tools", "supports_thinking"}

    def test_model_catalog_does_not_import_pricing(self) -> None:
        source = Path("packages/core/model_catalog.py").read_text()
        tree = ast.parse(source)
        imported_modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.add(node.module)
            elif isinstance(node, ast.Import):
                imported_modules.update(alias.name for alias in node.names)
        assert "pricing" not in imported_modules
        assert not any("pricing" in m for m in imported_modules)

    def test_pricing_does_not_import_model_catalog(self) -> None:
        source = Path("packages/core/pricing.py").read_text()
        assert "model_catalog" not in source

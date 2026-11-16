import asyncio
import json
import sys
from pathlib import Path

import pytest

from plugin_platform.manifest import PluginValidationError, validate_manifest
from plugin_platform.middleware import PluginMiddleware
from plugin_platform.provider import PluginCommandRunner, PluginProviderUpstream
from plugin_platform.store import PluginIntegrityError, PluginStore


def _plugin_source(tmp_path: Path, *, plugin_type: str = "provider") -> Path:
    source = tmp_path / "source"
    source.mkdir(exist_ok=True)
    script = source / "plugin.py"
    script.write_text(
        """
import json
import sys

request = json.load(sys.stdin)
action = request["action"]
if action == "complete":
    print(json.dumps({
        "id": "plugin-completion",
        "object": "chat.completion",
        "created": 1,
        "model": request["model"],
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "plugin ok"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1}
    }))
elif action == "before_request":
    payload = request["payload"]
    payload["plugin_seen"] = True
    print(json.dumps(payload))
elif action == "on_event":
    print(json.dumps(request["event"]))
elif action == "after_response":
    response = request["response"]
    response["plugin_after"] = True
    print(json.dumps(response))
""",
        encoding="utf-8",
    )
    manifest = {
        "id": "demo-plugin",
        "name": "Demo Plugin",
        "version": "1.0.0",
        "type": plugin_type,
        "runtime": "python",
        "entrypoint": [sys.executable, "plugin.py"],
        "capabilities": (
            ["network", "gateway.middleware"]
            if plugin_type == "middleware"
            else ["network", "provider.complete"]
        ),
        "ui": {
            "pages": [{"id": "settings", "title": "Settings"}],
            "slots": [{"id": "provider-card", "title": "Provider card"}],
        },
    }
    (source / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
    return source


def test_plugin_install_integrity_disable_update_and_remove(tmp_path: Path) -> None:
    store = PluginStore(tmp_path / "plugins")
    installed = store.install(_plugin_source(tmp_path))

    assert installed["id"] == "demo-plugin"
    assert installed["enabled"] is True
    assert store.verify("demo-plugin")["ok"] is True
    assert store.list_plugins()[0]["ui"]["slots"][0]["id"] == "provider-card"

    store.set_enabled("demo-plugin", False)
    assert store.list_plugins()[0]["enabled"] is False

    plugin_script = store.root / "demo-plugin" / "plugin.py"
    plugin_script.write_text("tampered", encoding="utf-8")
    with pytest.raises(PluginIntegrityError):
        store.verify("demo-plugin")

    updated = store.install(_plugin_source(tmp_path), allow_update=True)
    assert updated["enabled"] is False
    assert store.verify("demo-plugin")["ok"] is True
    assert store.remove("demo-plugin") is True
    assert store.list_plugins() == []


def test_plugin_manifest_rejects_path_escape_and_unknown_capability(
    tmp_path: Path,
) -> None:
    with pytest.raises(PluginValidationError, match="entrypoint"):
        validate_manifest(
            {
                "id": "bad",
                "name": "Bad",
                "version": "1",
                "type": "provider",
                "runtime": "bun",
                "entrypoint": ["bun", "../../escape.js"],
                "capabilities": [],
            }
        )
    with pytest.raises(PluginValidationError, match="capability"):
        validate_manifest(
            {
                "id": "bad",
                "name": "Bad",
                "version": "1",
                "type": "provider",
                "runtime": "bun",
                "entrypoint": ["bun", "index.js"],
                "capabilities": ["root-shell"],
            }
        )


def test_provider_plugin_executes_json_contract(tmp_path: Path) -> None:
    store = PluginStore(tmp_path / "plugins")
    store.install(_plugin_source(tmp_path))
    manifest = store.get_plugin("demo-plugin")
    upstream = PluginProviderUpstream(
        manifest,
        runner=PluginCommandRunner(store.root / "demo-plugin", timeout_seconds=5),
    )

    response = asyncio.run(
        upstream.complete(
            type("Resolved", (), {"model_id": "gpt-5"})(),
            {"messages": [{"role": "user", "content": "hello"}]},
        )
    )

    assert response["choices"][0]["message"]["content"] == "plugin ok"


def test_middleware_plugin_implements_hooks(tmp_path: Path) -> None:
    store = PluginStore(tmp_path / "plugins")
    store.install(_plugin_source(tmp_path, plugin_type="middleware"))
    manifest = store.get_plugin("demo-plugin")
    middleware = PluginMiddleware(
        manifest,
        runner=PluginCommandRunner(store.root / "demo-plugin", timeout_seconds=5),
    )

    async def run():
        request = await middleware.before_request(
            {"model": "mock/model"}, {"request_id": "req"}
        )
        event = await middleware.on_event(
            {"choices": []}, {"request_id": "req"}
        )
        response = await middleware.after_response(
            {"id": "response"}, {"request_id": "req"}
        )
        return request, event, response

    request, event, response = asyncio.run(run())
    assert request["plugin_seen"] is True
    assert event == {"choices": []}
    assert response["plugin_after"] is True

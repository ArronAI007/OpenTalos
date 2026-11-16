import datetime
import json
from pathlib import Path

import pytest

from subscriptions.service import SubscriptionInventory, SubscriptionValidationError
from subscriptions.store import SubscriptionStore


def test_inventory_discovers_signed_in_accounts_without_credentials(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    (home / ".claude" / ".credentials.json").write_text(
        json.dumps({"access_token": "claude-secret", "email": "alice@example.com"}),
        encoding="utf-8",
    )
    (home / ".codex").mkdir(parents=True)
    (home / ".codex" / "auth.json").write_text(
        json.dumps(
            {
                "tokens": {
                    "access_token": "codex-secret",
                    "account_id": "acct-123",
                }
            }
        ),
        encoding="utf-8",
    )
    (home / ".config" / "gh").mkdir(parents=True)
    (home / ".config" / "gh" / "hosts.yml").write_text(
        "github.com:\n  user: alice\n  oauth_token: gh-secret\n",
        encoding="utf-8",
    )
    store = SubscriptionStore(tmp_path / "subscriptions.db")
    inventory = SubscriptionInventory(store, home=home, platform_name="linux")

    accounts = inventory.discover()
    rendered = json.dumps(accounts, ensure_ascii=False)

    assert {account["provider"] for account in accounts} == {
        "claude",
        "codex",
        "github-copilot",
    }
    assert "claude-secret" not in rendered
    assert "codex-secret" not in rendered
    assert "gh-secret" not in rendered
    assert all(account["signed_in"] for account in accounts)
    assert all(account["quota"]["status"] == "unknown" for account in accounts)


def test_subscription_export_requires_credential_acknowledgement(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    (home / ".codex").mkdir(parents=True)
    (home / ".codex" / "auth.json").write_text("{}", encoding="utf-8")
    store = SubscriptionStore(tmp_path / "subscriptions.db")
    inventory = SubscriptionInventory(store, home=home, platform_name="linux")
    inventory.discover()

    metadata = inventory.export_bundle()
    assert metadata["warning"]
    assert "credentials" not in metadata

    with pytest.raises(SubscriptionValidationError, match="acknowledge"):
        inventory.export_bundle(include_credentials=True)

    with_credentials = inventory.export_bundle(
        include_credentials=True,
        acknowledge_credentials=True,
    )
    assert with_credentials["credentials"]


@pytest.mark.asyncio
async def test_warmup_scheduler_runs_due_schedules_once(tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / ".codex").mkdir(parents=True)
    (home / ".codex" / "auth.json").write_text("{}", encoding="utf-8")
    store = SubscriptionStore(tmp_path / "subscriptions.db")
    inventory = SubscriptionInventory(store, home=home, platform_name="linux")
    account = inventory.discover()[0]
    schedule = inventory.schedule_warmup(
        account["id"],
        mode="daily",
        at_time="08:00",
    )
    calls = []

    now = datetime.datetime.fromisoformat(schedule["next_run_at"])
    ran = await inventory.run_due_warmups(
        now=now,
        warm=lambda item: calls.append(item["id"]),
    )
    again = await inventory.run_due_warmups(
        now=now + datetime.timedelta(minutes=1),
        warm=lambda item: calls.append(item["id"]),
    )

    assert ran == 1
    assert again == 0
    assert calls == [account["id"]]

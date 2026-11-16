from pathlib import Path

from gateway.request_log import GatewayRequestLog


def test_gateway_request_log_records_and_lists_requests(tmp_path: Path) -> None:
    log = GatewayRequestLog(tmp_path / "gateway.db")
    created = log.start(
        model_requested="openai/gpt-4o",
        stream=True,
        client="test",
    )
    log.finish(
        created["id"],
        status="ok",
        model_resolved="gpt-4o",
        provider="openai",
        account_name="Primary",
        http_status=200,
        duration_ms=42,
        input_tokens=10,
        output_tokens=5,
    )
    log.set_routing_trace(
        created["id"],
        {"mode": "order", "attempts": [{"account": "Primary", "status": 429}]},
    )

    entries = log.list(limit=10)
    assert entries[0]["id"] == created["id"]
    assert entries[0]["model_requested"] == "openai/gpt-4o"
    assert entries[0]["input_tokens"] == 10
    assert entries[0]["total_tokens"] == 15
    assert entries[0]["routing_trace"]["mode"] == "order"

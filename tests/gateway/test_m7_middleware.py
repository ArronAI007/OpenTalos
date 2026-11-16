import asyncio

from gateway.middleware import GatewayMiddlewarePipeline


class RewriteMiddleware:
    def __init__(self) -> None:
        self.events = []

    async def before_request(self, payload, context):
        payload = dict(payload)
        payload["metadata"] = {"rewritten": True}
        return payload

    async def on_event(self, event, context):
        self.events.append(event)
        return event

    async def after_response(self, response, context):
        response = dict(response)
        response["middleware"] = "rewrite"
        return response


class SlowMiddleware:
    async def before_request(self, payload, context):
        await asyncio.sleep(1)
        return payload


class BrokenMiddleware:
    async def before_request(self, payload, context):
        raise RuntimeError("plugin failed")


def test_middleware_pipeline_rewrites_request_response_and_events() -> None:
    rewrite = RewriteMiddleware()
    pipeline = GatewayMiddlewarePipeline([rewrite])

    async def run():
        request = await pipeline.before_request(
            {"model": "openai/gpt-5"}, {"request_id": "req"}
        )
        event = await pipeline.on_event({"choices": []}, {"request_id": "req"})
        response = await pipeline.after_response({"id": "r"}, {"request_id": "req"})
        return request, event, response

    request, event, response = asyncio.run(run())

    assert request["metadata"]["rewritten"] is True
    assert event == {"choices": []}
    assert response["middleware"] == "rewrite"
    assert rewrite.events == [{"choices": []}]


def test_middleware_timeout_and_errors_fail_open_by_default() -> None:
    pipeline = GatewayMiddlewarePipeline(
        [SlowMiddleware(), BrokenMiddleware()],
        timeout_seconds=0.01,
        fail_open=True,
    )

    result = asyncio.run(
        pipeline.before_request({"model": "openai/gpt-5"}, {"request_id": "req"})
    )

    assert result == {"model": "openai/gpt-5"}
    assert len(pipeline.errors) == 2

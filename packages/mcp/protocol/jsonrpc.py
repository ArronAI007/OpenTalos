"""JSON-RPC 2.0 消息类型——不依赖任何 MCP 专用语义，纯协议层。"""
from dataclasses import dataclass
from enum import IntEnum
from typing import Any


class JSON_RPC_ERROR_CODES(IntEnum):
    PARSE_ERROR = -32700
    INVALID_REQUEST = -32600
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603


@dataclass
class JsonRpcErrorObject:
    code: int
    message: str
    data: Any | None = None


@dataclass
class JsonRpcRequest:
    id: int
    method: str
    params: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        message: dict[str, Any] = {"jsonrpc": "2.0", "id": self.id, "method": self.method}
        if self.params is not None:
            message["params"] = self.params
        return message


@dataclass
class JsonRpcNotification:
    method: str
    params: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        message: dict[str, Any] = {"jsonrpc": "2.0", "method": self.method}
        if self.params is not None:
            message["params"] = self.params
        return message


@dataclass
class JsonRpcResponse:
    """`result`/`error` 二选一，不可同时非 None（校验见 parse_jsonrpc_message）。"""

    id: int
    result: Any | None = None
    error: JsonRpcErrorObject | None = None

    def to_dict(self) -> dict[str, Any]:
        message: dict[str, Any] = {"jsonrpc": "2.0", "id": self.id}
        if self.error is not None:
            message["error"] = {"code": self.error.code, "message": self.error.message}
            if self.error.data is not None:
                message["error"]["data"] = self.error.data
        else:
            message["result"] = self.result
        return message


def is_jsonrpc_request(message: dict[str, Any]) -> bool:
    return "method" in message and "id" in message


def is_jsonrpc_notification(message: dict[str, Any]) -> bool:
    return "method" in message and "id" not in message


def is_jsonrpc_response(message: dict[str, Any]) -> bool:
    return "id" in message and "method" not in message and ("result" in message or "error" in message)


class MalformedJsonRpcMessageError(ValueError):
    """消息既不是合法的请求/通知/响应——校验失败,不是协议语义错误。"""


def parse_jsonrpc_message(
    message: dict[str, Any],
) -> JsonRpcRequest | JsonRpcNotification | JsonRpcResponse:
    if is_jsonrpc_response(message):
        has_result = "result" in message
        has_error = "error" in message
        if has_result == has_error:
            raise MalformedJsonRpcMessageError(
                f"response must have exactly one of result/error, got: {message!r}"
            )
        if has_error:
            error_data = message["error"]
            return JsonRpcResponse(
                id=message["id"],
                error=JsonRpcErrorObject(
                    code=error_data["code"], message=error_data["message"], data=error_data.get("data")
                ),
            )
        return JsonRpcResponse(id=message["id"], result=message["result"])
    if is_jsonrpc_request(message):
        return JsonRpcRequest(id=message["id"], method=message["method"], params=message.get("params"))
    if is_jsonrpc_notification(message):
        return JsonRpcNotification(method=message["method"], params=message.get("params"))
    raise MalformedJsonRpcMessageError(f"not a valid JSON-RPC request/notification/response: {message!r}")

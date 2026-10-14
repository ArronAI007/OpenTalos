"""MCP 演示/测试用的最小 server：暴露一个真实调用 wttr.in 的天气查询工具。

默认 stdio 模式（被当子进程启动，真机验证和单测的 stdio 传输都靠它）；传 --http 则切换成
监听 HTTP 的模式，独立进程手动起来测 HTTP/SSE 传输。两种模式共用同一份工具定义，不需要
为两种传输方式各写一个 server。
"""
import argparse

import httpx
from mcp.server import MCPServer

server = MCPServer("opentalos-demo-weather")


@server.tool()
async def get_weather(city: str) -> str:
    """查询某个城市当前天气（调用 wttr.in，免费无需 Key）。"""
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(f"https://wttr.in/{city}", params={"format": "3"})
        response.raise_for_status()
        return response.text.strip()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--http", action="store_true")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if args.http:
        server.run(transport="streamable-http", port=args.port)
    else:
        server.run(transport="stdio")


if __name__ == "__main__":
    main()

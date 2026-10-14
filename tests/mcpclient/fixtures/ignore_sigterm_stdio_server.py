"""测试夹具：忽略 SIGTERM，只在收到 SIGKILL 时才会退出；不响应 stdin 关闭（EOF）。
用于验证 StdioTransport.close() 的"stdin 关闭宽限期 → SIGTERM → SIGKILL"完整级联。"""
import signal
import time

signal.signal(signal.SIGTERM, signal.SIG_IGN)

while True:
    time.sleep(1)

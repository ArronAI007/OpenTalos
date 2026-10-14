"""测试夹具：拉起一个孙进程（不单独 detach，继承同一个进程组），自己响应普通终止信号。
用于验证关闭连接时，进程组清理会连带清理孙进程，不只是清理外层包装进程。"""
import subprocess
import sys
import time

subprocess.Popen(
    [sys.executable, "-c", "import time; time.sleep(120)", "mcp-test-grandchild-marker"]
)

while True:
    time.sleep(1)

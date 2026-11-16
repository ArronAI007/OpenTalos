# OpenTalos Desktop Shell

M1 桌面骨架使用 pywebview + pystray：

- 启动或复用现有 FastAPI 与 Next.js 服务。
- 主窗口通过系统 WebView 加载现有 OpenTalos Web UI。
- 系统托盘菜单提供打开主窗口、查看 API/Web 健康状态、重启服务和退出。
- 文件锁保证单实例，并通过激活文件转发第二次启动。

运行：

```bash
uv run python -m apps.desktop
```

使用已启动的服务：

```bash
uv run python -m apps.desktop --no-services
```

无界面烟测：

```bash
uv run python -m apps.desktop --no-services --no-tray --smoke-test
```

桌面日志位于 `.data/logs/desktop-api.log` 和 `.data/logs/desktop-web.log`。

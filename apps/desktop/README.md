# OpenTalos Desktop Shell

M1 桌面骨架使用 pywebview + pystray：

- 启动或复用现有 FastAPI 与 Next.js 服务。
- 启动 `:3421` OpenAI-compatible Gateway。
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

桌面日志位于 `.data/logs/desktop-api.log`、`.data/logs/desktop-gateway.log`
和 `.data/logs/desktop-web.log`。

## 安装发行版

- macOS：打开 `OpenTalos-<version>-macos-<arch>.dmg`，将 `OpenTalos.app`
  拖入 `Applications`。
- Windows：运行 `OpenTalos-<version>-windows-x86_64-setup.exe`。
- Linux：安装 `OpenTalos-<version>-linux-x86_64.deb`，然后从应用菜单启动。

发行包内置 Python、Node.js 和 Next.js standalone 运行时，不要求用户预装
Python、Node 或 pnpm。完整构建、签名、公证和自动更新说明见
[`release/README.md`](../../release/README.md)。

保留数据卸载：

```bash
OpenTalos --uninstall --keep-data --yes
```

同时删除本地数据：

```bash
OpenTalos --uninstall --purge --yes
```

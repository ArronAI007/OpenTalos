# M1 桌面骨架

**状态**: Skeleton Complete

**日期**: 2026-11-16

## 目标

建立 OpenTalos 的第一个 Python 桌面闭环：

- 启动或复用现有 FastAPI 与 Next.js。
- 使用系统 WebView 加载当前 OpenTalos Web UI。
- 提供系统托盘菜单。
- 提供单实例启动和第二次启动激活。
- 在退出或启动失败时清理子进程组。

## 桌面技术选择

计划中的首选 PySide6 在当前 Intel macOS 环境不可稳定安装：Python 只声明
`macosx-10.15-x86_64` 平台标签，而仍支持该硬件的 PySide6 wheel 最低要求 macOS 11/12，
Qt Addons 下载也超时。

因此 M1 使用：

- `pywebview 6.2.x`：macOS 使用 WKWebView，Windows 使用 WebView2，Linux 使用 WebKitGTK。
- `pystray 0.19.x`：系统托盘与菜单。
- Python 文件锁与激活文件：跨平台单实例协调。

业务层与桌面壳解耦。后续平台基线允许时，可替换桌面壳而不改动服务监督器、配置层和控制器。

## 代码结构

| 文件 | 职责 |
|---|---|
| `apps/desktop/config.py` | 端口、URL、命令、环境和启动超时 |
| `apps/desktop/supervisor.py` | API/Web 启动、健康检查、日志、进程组清理 |
| `apps/desktop/single_instance.py` | 文件锁、激活消息、第二次启动转发 |
| `apps/desktop/controller.py` | 主窗口、托盘、生命周期和服务协调 |
| `apps/desktop/tray.py` | 系统托盘菜单与健康状态 |
| `apps/desktop/main.py` | pywebview 应用入口 |

## 运行方式

完整桌面：

```bash
uv run python -m apps.desktop
```

仅托盘启动：

```bash
uv run python -m apps.desktop --tray-only
```

使用已有服务：

```bash
uv run python -m apps.desktop --no-services
```

烟测：

```bash
uv run python -m apps.desktop --no-services --no-tray --smoke-test
```

服务日志：

```text
.data/logs/desktop-api.log
.data/logs/desktop-web.log
```

## 已验证

- 13 个桌面单元测试通过。
- 真实 pywebview 窗口创建和自动销毁通过。
- 系统托盘初始化烟测通过。
- API、Next.js、WebView 端到端烟测通过。
- 烟测结束后 API `:8400` 和 Web `:3010` 均已释放。
- 服务按进程组终止，修复了 Next.js 包装进程退出后子进程遗留的问题。

## M1 尚未完成

以下能力仍保留为后续工作，不把骨架宣称为完整 M1：

- 真正的紧凑快速面板，而非托盘菜单状态区。
- 全局快捷键和快捷键冲突检测。
- `opentalos://` 系统协议注册。
- 开机启动管理。
- 原生通知权限和点击路由。
- 窗口置顶、多窗口和托盘动画。
- 自动崩溃重启和崩溃循环保护。
- 三平台打包、签名和安装验证。

## 验收命令

```bash
.venv/bin/python -m pytest -p no:capture tests/apps/desktop -q
uv run python -m apps.desktop --no-services --no-tray --smoke-test
```

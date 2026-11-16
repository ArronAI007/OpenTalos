# M8 Release：跨平台桌面发行

**状态**: Implemented

## 目标

把 OpenTalos 从源码运行形态交付为可安装的 macOS、Windows 和 Linux
桌面应用，同时保留本地 Python 服务、Next.js Web UI 和现有数据。

## 交付项

- macOS：签名 `.app`、压缩 `.dmg`、Applications 拖放链接和卸载脚本。
- Windows：PyInstaller one-folder 应用和 Inno Setup `.exe` 安装器。
- Linux：可选 AppImage 或 `.deb`；M8 采用 `.deb`，包含桌面入口、图标和
  维护脚本。
- 内置 Python、Node.js 和 Next.js standalone，不要求用户预装运行时。
- OpenTalos 应用图标：SVG、PNG、ICO、ICNS。
- Apple Developer ID 签名/公证、Windows Authenticode 和 Linux SHA-256
  发布脚本。
- Ed25519 签名更新清单、SHA-256/大小校验、原子暂存、应用内检查和
  重启安装。
- 平台标准用户数据目录、首次迁移备份、schema 降级保护和保留/清除数据
  两种卸载流程。
- GitHub Actions 多平台矩阵、release artifact、构建来源证明和自动发布。
- 第三方许可证清单与发行构建文档。

## 安全约束

- 更新清单必须使用 Ed25519 签名；更新包必须同时通过 manifest 签名、
  SHA-256 和大小校验。
- 私有更新密钥和平台签名证书只存在 CI secrets，不进入仓库或安装包。
- 默认卸载保留用户数据；`--purge` 是显式删除选项。
- 删除应用数据前恢复 Agent 托管配置快照。

## 验证

- `tests/release` 覆盖路径、迁移、更新、安装请求和卸载。
- Python API/desktop/release 回归通过。
- Vitest 185 项、ESLint 和 Next.js webpack production build 通过。
- macOS 实机构建生成 `OpenTalos.app` 和 `.dmg`。
- 冻结应用通过 API、Gateway、内置 Node/Next 和 pywebview 端到端 smoke。
- DMG 已验证包含应用、`Applications` 链接和卸载脚本。

正式 Developer ID 签名、Apple notarization 和 Windows Authenticode
需要在发布仓库配置相应 secrets 后由 CI 完成。

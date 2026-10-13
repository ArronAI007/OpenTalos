# Contract: `scripts/check_core_boundary.py`

## 调用方式

```bash
.venv/bin/python scripts/check_core_boundary.py [--package PATH]
```

- `--package PATH`：可选，默认 `packages/core`。指向要检查的包目录。路径必须存在且是目录，否则立
  即报错退出（不静默跳过——对应 constitution 的"输入必须校验"原则）。

## 输出与退出码

| 场景 | 退出码 | stdout |
|------|--------|--------|
| 没有发现任何违规导入 | `0` | `OK: packages/core 未依赖任何其他 packages/* 目录` |
| 发现一处或多处违规导入 | `1` | 每处违规一行：`<文件路径>:<行号>: 导入了 "<被导入的顶层包名>"` |
| 传入的 `--package` 路径不存在/不是目录 | `2` | `ERROR: <路径> 不是一个有效目录` |

退出码按"是否发现问题"分层（0=干净，1=发现违规，2=工具自身用法错误），对应 spec 的 Edge Case 决
议：调用方（包括人和 CI）要能区分"检查工具本身跑不起来"（退出码 2，或非 0/1/2 的未捕获异常）和
"检查跑起来了但发现了违规"（退出码 1）。

## 判定逻辑的契约（不是实现细节，是行为承诺）

- 只要被导入模块的顶层包名不等于 `core` 本身、不是 Python 标准库、也不在 `pyproject.toml`
  `[project].dependencies` 列出的第三方包名单里，就判定为违规——新增一个今天还不存在的
  `packages/some-new-feature` 包，不需要改这个脚本就能被检出（对应 FR-003）。
- 只扫描 `--package` 指向目录下的 `.py` 文件本身的顶层 `import`/`from ... import` 语句；不递归分
  析被导入模块内部又导入了什么（即不做传递闭包分析——只关心 `packages/core` 自己写了什么导入语
  句）。

## 供 pytest 复用的契约

脚本的核心检测函数必须能被 `import` 后直接调用（不只是作为 CLI 入口），函数签名形如：

```python
def find_boundary_violations(package_dir: Path) -> list[Violation]
```

其中 `Violation` 至少包含 `file: Path`、`line: int`、`imported_package: str` 三个字段，供
`tests/test_check_core_boundary.py` 和 `tests/core/` 下的边界回归测试直接断言，而不需要去解析 CLI
的 stdout 文本。

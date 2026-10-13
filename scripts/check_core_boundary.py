"""边界检查：扫描 packages/core 下所有 .py 文件的顶层 import 语句，报告任何对其他
packages/* 目录的直接依赖。白名单逻辑（允许 stdlib + pyproject.toml 声明的第三方依赖 +
包自身的相对导入），而不是维护一份"已知违规包名单"——这样新增一个今天还不存在的功能包时依然有效。

用法见 ../specs/001-core-isolation-selftest/contracts/boundary-check-cli.md。
"""
import argparse
import ast
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent

# 少数 PyPI 发行名和实际 import 名不一致的情况（本仓库 pyproject.toml 里出现过的）。
_PYPI_TO_IMPORT_NAME = {
    "python-dotenv": "dotenv",
    "pyyaml": "yaml",
    "python-multipart": "multipart",
    "a2a-sdk": "a2a",
}


@dataclass
class Violation:
    file: Path
    line: int
    imported_package: str


def _allowed_third_party_names(repo_root: Path) -> set[str]:
    data = tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))
    names: set[str] = set()
    for raw in data["project"]["dependencies"]:
        # "uvicorn[standard]>=0.32" -> "uvicorn"；"python-dotenv>=1.0" -> "python-dotenv"
        name = raw.split("[")[0]
        for sep in ("==", ">=", "<=", "~=", ">", "<"):
            name = name.split(sep)[0]
        name = name.strip()
        import_name = _PYPI_TO_IMPORT_NAME.get(name, name).replace("-", "_")
        names.add(import_name)
    return names


def find_boundary_violations(package_dir: Path, *, repo_root: Path | None = None) -> list[Violation]:
    """扫描 package_dir 下每个 .py 文件，返回所有对"允许列表之外的顶层模块"的导入。

    允许列表 = Python 标准库 + repo_root（默认本仓库根目录）的 pyproject.toml 声明的第三方依赖 +
    package_dir 自身的目录名（供绝对自引用）。相对导入（from . import x / from .foo import x）
    永远被视为包内引用，不检查。
    """
    if not package_dir.is_dir():
        raise FileNotFoundError(f"{package_dir} is not a directory")

    repo_root = repo_root or _REPO_ROOT
    allowed = _allowed_third_party_names(repo_root) | set(sys.stdlib_module_names) | {package_dir.name}

    violations: list[Violation] = []
    for path in sorted(package_dir.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    if top not in allowed:
                        violations.append(Violation(file=path, line=node.lineno, imported_package=top))
            elif isinstance(node, ast.ImportFrom):
                if node.level and node.level > 0:
                    continue
                if node.module is None:
                    continue
                top = node.module.split(".")[0]
                if top not in allowed:
                    violations.append(Violation(file=path, line=node.lineno, imported_package=top))
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="检查 packages/core 是否依赖了其他 packages/* 目录")
    parser.add_argument("--package", default="packages/core", help="要检查的包目录，默认 packages/core")
    args = parser.parse_args(argv)

    package_dir = Path(args.package)
    if not package_dir.is_dir():
        print(f"ERROR: {package_dir} 不是一个有效目录")
        return 2

    violations = find_boundary_violations(package_dir)
    if not violations:
        print(f"OK: {package_dir} 未依赖任何其他 packages/* 目录")
        return 0

    for violation in violations:
        print(f'{violation.file}:{violation.line}: 导入了 "{violation.imported_package}"')
    return 1


if __name__ == "__main__":
    sys.exit(main())

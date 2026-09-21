import sys
from pathlib import Path

# packages/ 本身加进 sys.path——每个模块目录（skill/、core/、agents/...）本身就是一个用目录名
# 命名的 Python 包（各自有 __init__.py），所以测试里用 `from skill.discovery import ...` 这种带
# 包名前缀的写法，不同模块之间不会因为同名文件（比如都叫 models.py）互相冲突。
#
# 没有用 pytest 的 `pythonpath` ini 选项——在这个仓库实际安装的 pytest 9.1.1 上实测不生效
# （sys.path 里始终没有 packages/），改用最直接可靠、不依赖 pytest 具体版本行为的 conftest.py
# 手动插入方式。
_PACKAGES_DIR = Path(__file__).resolve().parent.parent / "packages"
if str(_PACKAGES_DIR) not in sys.path:
    sys.path.insert(0, str(_PACKAGES_DIR))

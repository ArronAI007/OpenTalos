import json
from pathlib import Path

_ENCODING = "utf-8"


def load_my_skills(store_path: Path, all_skill_names: list[str]) -> set[str]:
    """读取已添加技能名集合。文件不存在时，用当前发现的全部技能名初始化并写盘
    （不是硬编码某几个名字——首次访问时"现有的全部算已添加"，之后新增的技能不会自动进来）。"""
    if not store_path.is_file():
        save_my_skills(store_path, set(all_skill_names))
        return set(all_skill_names)
    return set(json.loads(store_path.read_text(encoding=_ENCODING)))


def save_my_skills(store_path: Path, names: set[str]) -> None:
    store_path.parent.mkdir(parents=True, exist_ok=True)
    store_path.write_text(json.dumps(sorted(names)), encoding=_ENCODING)


def add_my_skill(store_path: Path, all_skill_names: list[str], name: str) -> bool:
    """返回 False 表示 name 不是一个真实存在的技能（调用方据此返回 404），不做任何写入。"""
    if name not in all_skill_names:
        return False
    names = load_my_skills(store_path, all_skill_names)
    names.add(name)
    save_my_skills(store_path, names)
    return True


def remove_my_skill(store_path: Path, all_skill_names: list[str], name: str) -> None:
    """幂等：name 本来就不在集合里也不报错。"""
    names = load_my_skills(store_path, all_skill_names)
    names.discard(name)
    save_my_skills(store_path, names)

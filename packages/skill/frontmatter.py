import yaml


def _split_frontmatter_block(content: str) -> tuple[str, str] | None:
    """从 SKILL.md 开头拆出 --- 包裹的原始 YAML 文本和正文；没有这个结构就返回 None。"""
    if not (content.startswith("---\n") or content.startswith("---\r\n")):
        return None
    parts = content.split("---", 2)
    if len(parts) < 3:
        return None
    return parts[1], parts[2].lstrip("\n")


def parse_frontmatter(content: str) -> tuple[dict, str]:
    """拆出 SKILL.md 开头的 YAML frontmatter（--- 包裹的那一段）和正文。
    没有 frontmatter、frontmatter 格式不对、或者解析出来不是一个字典时，返回 ({}, content 原样)。
    """
    split = _split_frontmatter_block(content)
    if split is None:
        return {}, content
    raw_yaml, body = split
    try:
        frontmatter = yaml.safe_load(raw_yaml)
    except yaml.YAMLError:
        return {}, content
    if not isinstance(frontmatter, dict):
        return {}, content
    return frontmatter, body


def extract_frontmatter_text(content: str) -> str | None:
    """返回 SKILL.md 开头 frontmatter 的原始 YAML 文本（未经解析，保留原文），
    没有 frontmatter 就返回 None——给"技能详情"里的 YAML 展示区用。"""
    split = _split_frontmatter_block(content)
    if split is None:
        return None
    raw_yaml, _ = split
    return raw_yaml.strip()

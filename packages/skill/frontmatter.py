import yaml


def parse_frontmatter(content: str) -> tuple[dict, str]:
    """拆出 SKILL.md 开头的 YAML frontmatter（--- 包裹的那一段）和正文。
    没有 frontmatter、frontmatter 格式不对、或者解析出来不是一个字典时，返回 ({}, content 原样)。
    """
    if not (content.startswith("---\n") or content.startswith("---\r\n")):
        return {}, content
    parts = content.split("---", 2)
    if len(parts) < 3:
        return {}, content
    try:
        frontmatter = yaml.safe_load(parts[1])
    except yaml.YAMLError:
        return {}, content
    if not isinstance(frontmatter, dict):
        return {}, content
    return frontmatter, parts[2].lstrip("\n")

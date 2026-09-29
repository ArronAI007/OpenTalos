from skill.frontmatter import extract_frontmatter_text, parse_frontmatter


def test_parse_frontmatter_returns_empty_dict_when_no_frontmatter():
    frontmatter, body = parse_frontmatter("# title\n\nSome text.\n")

    assert frontmatter == {}
    assert body == "# title\n\nSome text.\n"


def test_parse_frontmatter_extracts_valid_yaml():
    content = "---\nname: my-skill\ndescription: Does things.\n---\n# my-skill\n\nBody text.\n"

    frontmatter, body = parse_frontmatter(content)

    assert frontmatter == {"name": "my-skill", "description": "Does things."}
    assert body == "# my-skill\n\nBody text.\n"


def test_parse_frontmatter_falls_back_when_frontmatter_is_not_a_dict():
    content = "---\njust a string\n---\n# title\n"

    frontmatter, body = parse_frontmatter(content)

    assert frontmatter == {}
    assert body == content


def test_parse_frontmatter_falls_back_on_malformed_yaml():
    content = "---\nname: [unclosed\n---\n# title\n"

    frontmatter, body = parse_frontmatter(content)

    assert frontmatter == {}
    assert body == content


def test_extract_frontmatter_text_returns_the_raw_yaml_block():
    content = "---\nname: my-skill\ndescription: Does things.\n---\n# my-skill\n\nBody text.\n"

    assert extract_frontmatter_text(content) == "name: my-skill\ndescription: Does things."


def test_extract_frontmatter_text_returns_none_when_there_is_no_frontmatter():
    assert extract_frontmatter_text("# title\n\nSome text.\n") is None

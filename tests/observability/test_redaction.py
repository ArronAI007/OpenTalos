from observability.redaction import redact


def test_redact_masks_an_api_key():
    assert redact("key=sk-abc123XYZ") == "key=sk-***"


def test_redact_masks_a_bearer_token():
    assert redact("Authorization: Bearer abcDEF-123_456") == "Authorization: Bearer ***"


def test_redact_masks_a_bearer_prefixed_api_key_without_double_masking():
    # "Bearer sk-..." matches both the bearer-token and api-key patterns; it must come out
    # masked once, not with asterisks stacked from both substitutions.
    assert redact("Authorization: Bearer sk-abc123XYZ") == "Authorization: Bearer ***"


def test_redact_masks_a_home_directory_username():
    assert redact("/Users/alice/project") == "/Users/***/project"
    assert redact("/home/bob/project") == "/home/***/project"


def test_redact_recurses_into_dicts_and_lists():
    value = {"headers": {"Authorization": "Bearer secret-token"}, "paths": ["/Users/alice/x"]}
    result = redact(value)
    assert result == {"headers": {"Authorization": "Bearer ***"}, "paths": ["/Users/***/x"]}


def test_redact_leaves_non_string_scalars_untouched():
    assert redact(42) == 42
    assert redact(None) is None
    assert redact(3.14) == 3.14


def test_redact_leaves_text_without_secrets_unchanged():
    assert redact("just a normal sentence") == "just a normal sentence"

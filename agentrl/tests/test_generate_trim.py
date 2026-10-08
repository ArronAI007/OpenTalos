from training import _trim_to_first_answer


def test_trims_at_the_next_question_marker() -> None:
    text = "小明有3个苹果，又买了5个，所以一共有3+5=8个苹果。答案：8问题：小明有3个苹果，又买了5个，一共有多少个苹果？解答：小明有3个苹果"
    assert _trim_to_first_answer(text) == "小明有3个苹果，又买了5个，所以一共有3+5=8个苹果。答案：8"


def test_falls_back_to_last_sentence_boundary_when_no_question_marker() -> None:
    text = "小红有10颗糖，吃掉了4颗，还剩10-4=6颗。这个过程是正确的吗？为什么？答案：这个"
    assert _trim_to_first_answer(text) == "小红有10颗糖，吃掉了4颗，还剩10-4=6颗。这个过程是正确的吗？为什么？"


def test_returns_text_unchanged_when_it_already_ends_cleanly() -> None:
    text = "答案是8。"
    assert _trim_to_first_answer(text) == "答案是8。"


def test_returns_stripped_text_when_no_sentence_boundary_exists_at_all() -> None:
    text = "这是一段没有句末标点的文本"
    assert _trim_to_first_answer(text) == "这是一段没有句末标点的文本"

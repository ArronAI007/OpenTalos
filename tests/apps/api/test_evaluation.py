"""Agent 评估：测试用例 CRUD + LLM 裁判打分 + 单条评估执行，均遵循"失败不传染"的哲学。"""
from pathlib import Path

from evaluation import add_eval_case, load_eval_cases, remove_eval_case, save_eval_cases
from evaluation import EvalCase


def test_load_eval_cases_returns_empty_list_when_file_is_missing(tmp_path: Path) -> None:
    assert load_eval_cases(tmp_path / "eval_cases.json") == []


def test_add_eval_case_persists_and_round_trips(tmp_path: Path) -> None:
    store_path = tmp_path / "eval_cases.json"

    case = add_eval_case(store_path, "加法", "1+1等于几", "2")

    assert case.name == "加法"
    assert case.expected_answer == "2"
    assert load_eval_cases(store_path) == [case]


def test_add_eval_case_without_expected_answer(tmp_path: Path) -> None:
    store_path = tmp_path / "eval_cases.json"

    case = add_eval_case(store_path, "问候", "你好", None)

    assert case.expected_answer is None


def test_remove_eval_case_is_idempotent(tmp_path: Path) -> None:
    store_path = tmp_path / "eval_cases.json"
    case = add_eval_case(store_path, "加法", "1+1等于几", None)

    remove_eval_case(store_path, case.id)
    remove_eval_case(store_path, case.id)  # 第二次调用不应该报错

    assert load_eval_cases(store_path) == []


def test_save_and_load_eval_cases_round_trip(tmp_path: Path) -> None:
    store_path = tmp_path / "eval_cases.json"
    cases = [EvalCase(id="c1", name="a", instruction="ia", expected_answer=None)]

    save_eval_cases(store_path, cases)

    assert load_eval_cases(store_path) == cases

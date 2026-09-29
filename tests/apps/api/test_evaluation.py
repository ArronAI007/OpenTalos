"""Agent 评估：测试用例 CRUD + LLM 裁判打分 + 单条评估执行，均遵循"失败不传染"的哲学。"""
import asyncio
from pathlib import Path
from typing import Any

import pytest
from core.protocol import Completion, ToolCompletion
from db import ChatStore
from evaluation import add_eval_case, judge_reply, load_eval_cases, remove_eval_case, run_case, save_eval_cases
from evaluation import EvalCase, EvalScore
from runtime import ChatRuntime


@pytest.fixture
def store(tmp_path: Path) -> ChatStore:
    return ChatStore(tmp_path / "chat.db")


def _runtime(store: ChatStore, client, tmp_path: Path) -> ChatRuntime:
    return ChatRuntime(
        store, model_client=client, skill_service_url="http://127.0.0.1:1", trace_dir=tmp_path / "traces",
    )


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


class TestJudgeReply:
    def test_parses_a_well_formed_score(self, scripted_client) -> None:
        client = scripted_client(completions=[
            Completion(text='{"correctness": 5, "completeness": 4, "clarity": 3, "comment": "还行"}', model_id="mock-model"),
        ])
        score = asyncio.run(judge_reply(client, "1+1等于几", "2", "2"))
        assert score == EvalScore(correctness=5, completeness=4, clarity=3, comment="还行")

    def test_parses_json_wrapped_in_prose(self, scripted_client) -> None:
        client = scripted_client(completions=[
            Completion(
                text='好的，评分如下：\n{"correctness": 3, "completeness": 3, "clarity": 3, "comment": "一般"}\n供参考',
                model_id="mock-model",
            ),
        ])
        score = asyncio.run(judge_reply(client, "instruction", None, "reply"))
        assert score == EvalScore(correctness=3, completeness=3, clarity=3, comment="一般")

    def test_returns_none_on_malformed_json(self, scripted_client) -> None:
        client = scripted_client(completions=[Completion(text="不是 JSON", model_id="mock-model")])
        assert asyncio.run(judge_reply(client, "instruction", None, "reply")) is None

    def test_returns_none_on_missing_fields(self, scripted_client) -> None:
        client = scripted_client(completions=[Completion(text='{"correctness": 5}', model_id="mock-model")])
        assert asyncio.run(judge_reply(client, "instruction", None, "reply")) is None

    def test_returns_none_on_timeout(self, scripted_client) -> None:
        client = scripted_client()

        async def slow(_messages: list[dict[str, Any]], **_kwargs: Any) -> Completion:
            await asyncio.sleep(0.3)
            return Completion(text='{"correctness": 5, "completeness": 5, "clarity": 5, "comment": "x"}', model_id="mock-model")

        client.acomplete = slow  # type: ignore[method-assign]
        assert asyncio.run(judge_reply(client, "instruction", None, "reply", timeout=0.05)) is None


class TestRunCase:
    def test_captures_a_reply_and_judge_score(self, store, scripted_client, tmp_path) -> None:
        client = scripted_client(
            tool_completions=[ToolCompletion(text="42", requested_tools=[], model_id="mock-model")],
            completions=[Completion(text='{"correctness": 5, "completeness": 4, "clarity": 5, "comment": "good"}', model_id="mock-model")],
        )
        runtime = _runtime(store, client, tmp_path)
        case = EvalCase(id="c1", name="加法", instruction="1+1等于几", expected_answer="2")

        result = asyncio.run(run_case(runtime, "react", case))

        assert result.reply == "42"
        assert result.score == EvalScore(correctness=5, completeness=4, clarity=5, comment="good")
        assert result.error is None
        assert result.case_id == "c1"
        assert result.case_name == "加法"
        assert result.agent_type == "react"

    def test_created_task_is_archived_and_hidden_from_the_task_list(self, store, scripted_client, tmp_path) -> None:
        client = scripted_client(
            tool_completions=[ToolCompletion(text="ok", requested_tools=[], model_id="mock-model")],
            completions=[Completion(text='{"correctness": 3, "completeness": 3, "clarity": 3, "comment": "x"}', model_id="mock-model")],
        )
        runtime = _runtime(store, client, tmp_path)
        case = EvalCase(id="c1", name="用例", instruction="hi", expected_answer=None)

        asyncio.run(run_case(runtime, "react", case))

        assert store.list_tasks() == []  # 评估任务立即标 archived，不出现在默认任务列表

    def test_captures_an_error_without_raising(self, store, scripted_client, tmp_path) -> None:
        client = scripted_client(tool_completions=[])
        runtime = _runtime(store, client, tmp_path)
        case = EvalCase(id="c1", name="坏用例", instruction="hi", expected_answer=None)

        result = asyncio.run(run_case(runtime, "not-a-real-agent-type", case))

        assert result.reply is None
        assert result.score is None
        assert result.error is not None

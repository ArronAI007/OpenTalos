import httpx

from skill.client import SkillClient
from skill.tools import ReadSkillTool, RunSkillScriptTool
from tool.outcome import OutcomeStatus


def _build_client(handler) -> SkillClient:
    return SkillClient("http://skill.test", client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


def _ok_skill_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/skills/date":
        return httpx.Response(200, json={"name": "date", "content": "# date\n\nusage..."})
    if request.url.path == "/skills/date/run-script":
        return httpx.Response(200, json={"stdout": "2026-09-22\n", "stderr": "", "exit_code": 0, "timed_out": False})
    return httpx.Response(404, json={"detail": "Unknown skill."})


async def test_read_skill_returns_the_documentation():
    tool = ReadSkillTool(_build_client(_ok_skill_handler))

    outcome = await tool.acall({"skill_name": "date"})

    assert outcome.status is OutcomeStatus.OK
    assert outcome.output == "# date\n\nusage..."


async def test_read_skill_turns_a_service_error_into_an_error_outcome():
    tool = ReadSkillTool(_build_client(_ok_skill_handler))

    outcome = await tool.acall({"skill_name": "nope"})

    assert outcome.status is OutcomeStatus.ERROR
    assert "Unknown skill" in outcome.output


async def test_run_skill_script_returns_stdout_on_success():
    tool = RunSkillScriptTool(_build_client(_ok_skill_handler))

    outcome = await tool.acall({"skill_name": "date", "script_relative_path": "scripts/main.py"})

    assert outcome.status is OutcomeStatus.OK
    assert outcome.output == "2026-09-22\n"


async def test_run_skill_script_reports_exit_code_and_stderr_on_failure():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"stdout": "", "stderr": "boom", "exit_code": 1, "timed_out": False})

    tool = RunSkillScriptTool(_build_client(handler))

    outcome = await tool.acall({"skill_name": "date", "script_relative_path": "scripts/main.py"})

    assert outcome.status is OutcomeStatus.OK
    assert "code 1" in outcome.output
    assert "boom" in outcome.output


async def test_run_skill_script_reports_timeouts():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"stdout": "", "stderr": "", "exit_code": -1, "timed_out": True})

    tool = RunSkillScriptTool(_build_client(handler))

    outcome = await tool.acall({"skill_name": "date", "script_relative_path": "scripts/main.py"})

    assert outcome.status is OutcomeStatus.OK
    assert "timed out" in outcome.output


async def test_run_skill_script_turns_a_service_error_into_an_error_outcome():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    tool = RunSkillScriptTool(_build_client(handler))

    outcome = await tool.acall({"skill_name": "date", "script_relative_path": "scripts/main.py"})

    assert outcome.status is OutcomeStatus.ERROR
    assert "unreachable" in outcome.output


def test_run_skill_script_schema_types_args_as_a_string_array():
    schema = RunSkillScriptTool(_build_client(_ok_skill_handler)).to_function_schema()

    args = schema["function"]["parameters"]["properties"]["args"]
    assert args["type"] == "array"
    assert args["items"] == {"type": "string"}
    required = schema["function"]["parameters"]["required"]
    assert "skill_name" in required
    assert "script_relative_path" in required
    assert "args" not in required

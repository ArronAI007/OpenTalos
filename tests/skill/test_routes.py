import pytest
from fastapi.testclient import TestClient

from skill.main import app


@pytest.fixture
def client(monkeypatch, tmp_path):
    import skill.main as main_module
    monkeypatch.setattr(main_module, "MY_SKILLS_PATH", tmp_path / "my_skills.json")
    with TestClient(app) as test_client:
        yield test_client


def test_health(client: TestClient) -> None:
    assert client.get("/health").status_code == 200


def test_list_skills_includes_the_built_in_skills(client: TestClient) -> None:
    response = client.get("/skills")
    assert response.status_code == 200
    names = {s["name"] for s in response.json()["skills"]}
    assert {"csv-to-json", "date", "text-to-table"}.issubset(names)


def test_get_skill_returns_its_skill_md_content(client: TestClient) -> None:
    response = client.get("/skills/csv-to-json")
    assert response.status_code == 200
    assert "csv-to-json" in response.json()["content"]


def test_get_skill_returns_404_for_an_unknown_skill(client: TestClient) -> None:
    response = client.get("/skills/does-not-exist")
    assert response.status_code == 404


def test_run_script_executes_the_csv_to_json_skill_end_to_end(client: TestClient) -> None:
    response = client.post(
        "/skills/csv-to-json/run-script",
        json={"script_relative_path": "convert.py", "args": [], "input_text": "name,age\nAlice,30\n"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["exit_code"] == 0
    assert '"name"' in body["stdout"]
    assert "Alice" in body["stdout"]


def test_run_script_executes_the_date_skill_end_to_end(client: TestClient) -> None:
    response = client.post(
        "/skills/date/run-script",
        json={"script_relative_path": "scripts/main.py", "args": ["7"]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["exit_code"] == 0
    assert len(body["stdout"].strip()) == 10  # YYYY-MM-DD


def test_run_script_rejects_path_traversal(client: TestClient) -> None:
    response = client.post(
        "/skills/csv-to-json/run-script",
        json={"script_relative_path": "../../../etc/passwd", "args": []},
    )
    assert response.status_code == 422
    assert "outside" in response.text


def test_run_script_returns_422_for_an_unknown_skill(client: TestClient) -> None:
    response = client.post(
        "/skills/does-not-exist/run-script",
        json={"script_relative_path": "x.py", "args": []},
    )
    assert response.status_code == 422


def test_run_script_rejects_oversized_input_text(client: TestClient) -> None:
    response = client.post(
        "/skills/csv-to-json/run-script",
        json={"script_relative_path": "convert.py", "args": [], "input_text": "a" * 65_537},
    )
    assert response.status_code == 422
    assert "too large" in response.text


def test_github_scan_rejects_an_invalid_repo_url(client: TestClient) -> None:
    response = client.post("/github-import/scan", json={"repo_url": "not-a-url"})
    assert response.status_code == 400


def test_github_scan_returns_502_when_clone_fails(client: TestClient, monkeypatch) -> None:
    import skill.main as main_module

    async def fake_scan_github_repo(repo_url: str):
        from skill.github_import import GithubImportError
        raise GithubImportError("git clone 失败：boom")

    monkeypatch.setattr(main_module, "scan_github_repo", fake_scan_github_repo)

    response = client.post("/github-import/scan", json={"repo_url": "https://github.com/owner/repo"})
    assert response.status_code == 502
    assert "boom" in response.json()["detail"]


def test_github_scan_returns_candidates_on_success(client: TestClient, monkeypatch) -> None:
    import skill.main as main_module
    from skill.models import GithubSkillCandidate

    async def fake_scan_github_repo(repo_url: str):
        return [GithubSkillCandidate(relative_path="skills/alpha", name="alpha", description="Alpha thing.")]

    monkeypatch.setattr(main_module, "scan_github_repo", fake_scan_github_repo)

    response = client.post("/github-import/scan", json={"repo_url": "https://github.com/owner/repo"})
    assert response.status_code == 200
    assert response.json()["candidates"] == [
        {"relative_path": "skills/alpha", "name": "alpha", "description": "Alpha thing."}
    ]


def test_github_import_rejects_an_invalid_repo_url(client: TestClient) -> None:
    response = client.post("/github-import/import", json={"repo_url": "not-a-url", "relative_paths": []})
    assert response.status_code == 400


def test_list_skills_reports_added_status(client: TestClient) -> None:
    response = client.get("/skills")

    skills = {s["name"]: s["added"] for s in response.json()["skills"]}
    # client fixture 给了全新的临时 MY_SKILLS_PATH，首次访问会用当前全部技能名自动初始化，
    # 所以这几个内置技能这里应该都是 added=True。
    assert skills["date"] is True
    assert skills["csv-to-json"] is True


def test_add_my_skill_marks_it_added(client: TestClient) -> None:
    # client fixture 给的是全新临时 MY_SKILLS_PATH，首次访问会自动把所有内置技能标成已添加——
    # 先显式移除一次，才能真正验证 POST 让它从"未添加"变回"已添加"，而不是本来就是添加状态。
    client.delete("/my-skills/date")

    response = client.post("/my-skills/date")

    assert response.status_code == 200
    assert response.json() == {"added": True}
    assert client.get("/skills/date").status_code == 200


def test_add_my_skill_returns_404_for_an_unknown_skill(client: TestClient) -> None:
    response = client.post("/my-skills/does-not-exist")

    assert response.status_code == 404


def test_remove_my_skill_is_idempotent(client: TestClient) -> None:
    first = client.delete("/my-skills/date")
    second = client.delete("/my-skills/date")

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == {"added": False}


def test_get_skill_returns_404_when_not_added(client: TestClient) -> None:
    client.delete("/my-skills/date")

    response = client.get("/skills/date")

    assert response.status_code == 404


def test_run_script_returns_422_when_not_added(client: TestClient) -> None:
    client.delete("/my-skills/csv-to-json")

    response = client.post(
        "/skills/csv-to-json/run-script",
        json={"script_relative_path": "convert.py", "args": [], "input_text": "a,b\n1,2\n"},
    )

    assert response.status_code == 422


def test_github_import_returns_imported_and_skipped_on_success(client: TestClient, monkeypatch) -> None:
    import skill.main as main_module

    async def fake_import_github_skills(repo_url: str, relative_paths: list[str], skills_root):
        return ["alpha"], []

    monkeypatch.setattr(main_module, "import_github_skills", fake_import_github_skills)

    response = client.post(
        "/github-import/import",
        json={"repo_url": "https://github.com/owner/repo", "relative_paths": ["skills/alpha"]},
    )
    assert response.status_code == 200
    assert response.json() == {"imported": ["alpha"], "skipped": []}

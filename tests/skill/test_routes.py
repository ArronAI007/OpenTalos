import pytest
from fastapi.testclient import TestClient

from skill.main import app


@pytest.fixture
def client(monkeypatch, tmp_path):
    import skill.main as main_module
    monkeypatch.setattr(main_module, "MY_SKILLS_PATH", tmp_path / "my_skills.json")
    monkeypatch.setattr(main_module, "SKILL_TAGS_PATH", tmp_path / "skill_tags.json")
    monkeypatch.setattr(main_module, "SKILL_USAGE_PATH", tmp_path / "skill_usage.json")
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


def test_list_skills_reports_tags_and_usage_count(client: TestClient) -> None:
    response = client.get("/skills")

    skills = {s["name"]: s for s in response.json()["skills"]}
    # client fixture 给的是全新的临时存储，还没写过任何 tags/usage 数据，
    # 所以这里应该都是默认值：空标签、0 次使用。
    assert skills["date"]["tags"] == []
    assert skills["date"]["usage_count"] == 0


def test_run_script_increments_usage_count(client: TestClient) -> None:
    payload = {"script_relative_path": "convert.py", "args": [], "input_text": "a,b\n1,2\n"}

    client.post("/skills/csv-to-json/run-script", json=payload)
    client.post("/skills/csv-to-json/run-script", json=payload)

    response = client.get("/skills")
    skills = {s["name"]: s for s in response.json()["skills"]}
    assert skills["csv-to-json"]["usage_count"] == 2


def test_run_script_does_not_increment_usage_when_not_added(client: TestClient) -> None:
    client.delete("/my-skills/csv-to-json")

    client.post(
        "/skills/csv-to-json/run-script",
        json={"script_relative_path": "convert.py", "args": [], "input_text": "a,b\n1,2\n"},
    )

    client.post("/my-skills/csv-to-json")  # 加回来才能在 GET /skills 里看到它（未添加会被过滤成 404）
    response = client.get("/skills")
    skills = {s["name"]: s for s in response.json()["skills"]}
    assert skills["csv-to-json"]["usage_count"] == 0


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


def test_get_skill_detail_works_even_when_not_added(client: TestClient) -> None:
    client.delete("/my-skills/date")

    response = client.get("/skills/date/detail")

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "date"
    assert body["added"] is False
    assert "files" in body
    assert "updated_at" in body


def test_get_skill_detail_strips_frontmatter_from_the_skill_md_file_entry(
    client: TestClient, monkeypatch, tmp_path
) -> None:
    import skill.main as main_module

    skill_dir = tmp_path / "with-frontmatter"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: with-frontmatter\ndescription: Has frontmatter.\n---\n# with-frontmatter\n\nBody text.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(main_module, "SKILLS_ROOT", tmp_path)

    response = client.get("/skills/with-frontmatter/detail")

    assert response.status_code == 200
    files = {f["path"]: f["content"] for f in response.json()["files"]}
    assert "---" not in files["SKILL.md"]
    assert "name: with-frontmatter" not in files["SKILL.md"]
    assert files["SKILL.md"].startswith("# with-frontmatter")


def test_get_skill_detail_includes_every_file_in_the_skill_directory(
    client: TestClient, monkeypatch, tmp_path
) -> None:
    import skill.main as main_module

    skill_dir = tmp_path / "multi-file"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("# multi-file\n", encoding="utf-8")
    (skill_dir / "scripts").mkdir()
    (skill_dir / "scripts" / "main.py").write_text("print('hi')\n", encoding="utf-8")
    monkeypatch.setattr(main_module, "SKILLS_ROOT", tmp_path)

    response = client.get("/skills/multi-file/detail")

    assert response.status_code == 200
    files = {f["path"]: f["content"] for f in response.json()["files"]}
    assert files == {"SKILL.md": "# multi-file\n", "scripts/main.py": "print('hi')\n"}


def test_get_skill_detail_reports_the_raw_frontmatter_yaml_separately(
    client: TestClient, monkeypatch, tmp_path
) -> None:
    import skill.main as main_module

    skill_dir = tmp_path / "with-frontmatter"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: with-frontmatter\ndescription: Has frontmatter.\n---\n# with-frontmatter\n\nBody text.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(main_module, "SKILLS_ROOT", tmp_path)

    response = client.get("/skills/with-frontmatter/detail")

    assert response.status_code == 200
    assert response.json()["frontmatter_yaml"] == "name: with-frontmatter\ndescription: Has frontmatter."


def test_get_skill_detail_reports_none_frontmatter_yaml_when_there_is_no_frontmatter(
    client: TestClient,
) -> None:
    response = client.get("/skills/date/detail")

    assert response.status_code == 200
    assert response.json()["frontmatter_yaml"] is None


def test_get_skill_detail_returns_404_for_an_unknown_skill(client: TestClient) -> None:
    response = client.get("/skills/does-not-exist/detail")

    assert response.status_code == 404


def test_skill_upload_returns_the_extracted_name_on_success(client: TestClient, monkeypatch) -> None:
    import skill.main as main_module

    def fake_extract_uploaded_skill(file_bytes: bytes, skills_root):
        return "my-skill"

    monkeypatch.setattr(main_module, "extract_uploaded_skill", fake_extract_uploaded_skill)

    response = client.post(
        "/skill-upload",
        files={"file": ("my-skill.zip", b"fake zip bytes", "application/zip")},
    )

    assert response.status_code == 200
    assert response.json() == {"name": "my-skill"}


def test_skill_upload_returns_422_on_validation_failure(client: TestClient, monkeypatch) -> None:
    import skill.main as main_module
    from skill.skill_upload import SkillUploadError

    def fake_extract_uploaded_skill(file_bytes: bytes, skills_root):
        raise SkillUploadError("压缩包根目录下没有 SKILL.md。")

    monkeypatch.setattr(main_module, "extract_uploaded_skill", fake_extract_uploaded_skill)

    response = client.post(
        "/skill-upload",
        files={"file": ("bad.zip", b"fake zip bytes", "application/zip")},
    )

    assert response.status_code == 422
    assert "SKILL.md" in response.json()["detail"]

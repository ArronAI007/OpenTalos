import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
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

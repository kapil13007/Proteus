"""The HTTP API, end to end, the way the frontend uses it."""
import io
import time
import zipfile

import httpx
import pytest
from conftest import SAMPLE_ANSWERS, sample_bytes
from fastapi.testclient import TestClient

from app.config import settings
from app.github import publish
from app.main import app

PASSWORD = "Str0ng!pass"


@pytest.fixture
def client():
    with TestClient(app) as c:
        email = f"user{time.time_ns()}@example.com"
        assert c.post("/auth/register", json={"email": email, "password": PASSWORD}).status_code == 200
        assert c.post("/auth/login", json={"email": email, "password": PASSWORD}).status_code == 200
        yield c


def _upload(c: TestClient, **replace):
    files = {
        "source": ("source_schema.md", sample_bytes("source_schema.md")),
        "target": ("target_schema.md", sample_bytes("target_schema.md")),
        "sttm": ("sttm.xlsx", sample_bytes("sttm.xlsx")),
        "repo": ("folder_structure.md", sample_bytes("folder_structure.md")),
        "udf": ("functions.js", sample_bytes("functions.js")),
        "env": ("env_vars.js", sample_bytes("env_vars.js")),
    }
    files.update(replace)
    return c.post("/runs", files=files)


def _wait(c: TestClient, run_id: str, *statuses: str, timeout: float = 30) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        run = c.get(f"/runs/{run_id}").json()
        if run["status"] in statuses:
            return run
        time.sleep(0.1)
    raise AssertionError(f"run stuck in {run['status']}: {[e['text'] for e in run['feed']][-5:]}")


def test_requires_login():
    with TestClient(app) as c:
        assert c.get("/runs").status_code == 401
        assert c.get("/health").json() == {"ok": True}


def test_full_http_flow(client, fake_llm, empty_cache):
    fake_llm({**SAMPLE_ANSWERS, "weight": [{"kind": "sql", "sql": "CAST(weight_kg AS DATE)"}]})
    res = _upload(client)
    assert res.status_code == 200, res.text
    run_id = res.json()["run_id"]

    run = _wait(client, run_id, "awaiting_review", "failed")
    assert run["status"] == "awaiting_review"
    assert run["targetTable"] == "analytics.fct_clinical_patients"
    assert {d["targetField"] for d in run["decisions"] if d["status"] == "failed"} == {"weight"}
    email = next(d for d in run["decisions"] if d["targetField"] == "email_address")
    # record keys are camelCase, but data keys (source column names) are untouched
    assert email["examples"][0]["in"] == {"cust_email_01": "  John.DOE@Email.com "}
    assert run["conventions"]["stepFiles"]["read"] == "{table}_read.sqlx"
    assert {f["kind"] for f in run["files"]} == {"declaration", "source_params", "target_params",
                                                "read", "process", "write"}
    assert run["feed"] and run["metrics"]["llm"]["calls"] >= 1

    # approval is blocked while a column needs a human
    blocked = client.post(f"/runs/{run_id}/approve")
    assert blocked.status_code == 409 and "row(s) 6" in blocked.json()["detail"]

    # the reviewer fixes it with an override; the agent re-verifies
    assert client.post(f"/runs/{run_id}/revise", json={
        "overrides": [{"row": 6, "expression": "CAST(ROUND(weight_kg) AS INT64)"}]}).status_code == 200
    run = _wait(client, run_id, "awaiting_review", "failed")
    assert all(d["status"] == "ok" for d in run["decisions"])
    assert run["revisions"][0]["overrides"] == [6]

    assert client.post(f"/runs/{run_id}/approve").status_code == 200
    run = _wait(client, run_id, "succeeded", "failed")
    assert run["status"] == "succeeded", [e["text"] for e in run["feed"]][-6:]
    assert run["audit"]["rowsWritten"] == 15 and run["meta"]["approvedBy"].startswith("user")

    bundle = client.get(f"/runs/{run_id}/bundle.zip")
    names = zipfile.ZipFile(io.BytesIO(bundle.content)).namelist()
    assert "definitions/gold/fct_clinical_patients/fct_clinical_patients_write.sqlx" in names
    assert "MAPFLOW_DECISIONS.md" in names

    listed = client.get("/runs").json()
    assert listed[0]["id"] == run_id and "decisions" not in listed[0]  # list stays light

    status = client.get("/system/status")
    assert status.json()["warehouse"]["engine"].startswith("DuckDB") and status.json()["cache"]["entries"] >= 1
    assert settings.groq_api_key not in status.text and settings.session_secret not in status.text  # no secrets


def test_sample_inputs_are_served_from_a_whitelist(client):
    assert client.get("/samples").json()["udf"] == "functions.js"
    assert b"cleanEmail" in client.get("/samples/udf").content
    assert client.get("/samples/..%2F.env").status_code == 404


def test_bad_upload_is_rejected_immediately(client):
    res = _upload(client, target=("target_schema.md", b"no table heading here"))
    assert res.status_code == 400 and "must name its table" in res.json()["detail"]


def test_reject_is_terminal(client, fake_llm):
    fake_llm()
    run_id = _upload(client).json()["run_id"]
    _wait(client, run_id, "awaiting_review")
    assert client.post(f"/runs/{run_id}/reject", json={"feedback": "wrong target"}).status_code == 200
    run = client.get(f"/runs/{run_id}").json()
    assert run["status"] == "rejected" and run["meta"]["rejectFeedback"] == "wrong target"
    assert client.post(f"/runs/{run_id}/approve").status_code == 409


def test_publish_is_one_atomic_commit(monkeypatch):
    monkeypatch.setattr(settings, "github_token", "t")
    monkeypatch.setattr(settings, "github_repo", "me/models")
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        path = request.url.path
        if path.endswith("/git/ref/heads/main"):
            return httpx.Response(200, json={"object": {"sha": "parent123"}})
        if path.endswith("/git/commits/parent123"):
            return httpx.Response(200, json={"tree": {"sha": "tree0"}})
        if path.endswith("/git/trees"):
            return httpx.Response(201, json={"sha": "tree1"})
        if path.endswith("/git/commits"):
            return httpx.Response(201, json={"sha": "abcdef1234"})
        return httpx.Response(200, json={})

    res = publish([{"path": "a.sqlx", "content": "x"}, {"path": "b.js", "content": "y"}], "msg",
                  transport=httpx.MockTransport(handler))
    assert res["pushed"] and res["sha"] == "abcdef1" and res["files"] == 2
    assert [m for m, _ in seen] == ["GET", "GET", "POST", "POST", "PATCH"]


def test_publish_is_skipped_without_a_token(monkeypatch):
    monkeypatch.setattr(settings, "github_token", "")
    assert publish([], "m")["skipped"] is True

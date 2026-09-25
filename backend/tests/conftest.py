"""Test setup: isolated throwaway databases, no network, a scripted LLM.

Settings are read when app.config is imported, so the environment is set here,
before any test module imports the app.
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
_TMP = Path(tempfile.mkdtemp(prefix="mapflow-tests-"))
os.environ.update({
    "MAPFLOW_ENV_FILE": "",                # ignore backend/.env: tests never see real keys or settings
    "DATABASE_URL": f"sqlite:///{(_TMP / 'app.db').as_posix()}",
    "WAREHOUSE_PATH": str(_TMP / "warehouse.duckdb"),
    "SEED_DEMO_DATA": "true",
    "GROQ_API_KEY": "test-key-not-used",   # the client is replaced by FakeLLM in every test
    "GITHUB_TOKEN": "",                    # never publish from tests
    "GITHUB_REPO": "",
    "LLM_CACHE": "true",
    "MAX_REPAIR_ATTEMPTS": "3",
    "SESSION_SECRET": "test-secret-0123456789abcdef0123456789abcdef",
})
sys.path.insert(0, str(BACKEND))

import pytest  # noqa: E402

from app.database import LlmCacheEntry, SessionLocal, create_tables  # noqa: E402

create_tables()
SAMPLES = BACKEND / "sample_inputs"


def sample_text(name: str) -> str:
    return (SAMPLES / name).read_text(encoding="utf-8")


def sample_bytes(name: str) -> bytes:
    return (SAMPLES / name).read_bytes()


class FakeLLM:
    """Scripted stand-in for GroqClient. `answers` maps target column -> successive answers;
    the last answer repeats. Records every call so tests can assert on what was sent."""

    model = "fake-model"

    def __init__(self, answers: dict[str, list[dict]]):
        self.answers = {k: list(v) for k, v in answers.items()}
        self.calls: list[dict] = []

    def complete_json(self, system, user, schema, name, max_tokens):
        rows = [json.loads(line) for line in user.splitlines() if line.startswith('{"row"')]
        self.calls.append({"rows": [r["row"] for r in rows], "prompt": user})
        out = []
        for r in rows:
            seq = self.answers.get(r["target"])
            if not seq:
                continue
            answer = seq.pop(0) if len(seq) > 1 else seq[0]
            out.append({"row": r["row"], "udf": None, "args": [], "sql": None, "rationale": "scripted", **answer})
        usage = {"calls": 1, "promptTokens": len(user) // 4, "completionTokens": 60 * len(out),
                 "cachedTokens": 0, "reasoningTokens": 20, "latencyMs": 3}
        return {"mappings": out}, usage


# Answers a good model gives for the sample STTM. date_of_birth's first answer is a
# plain CAST that the dirty sample data breaks, which exercises the repair loop.
SAMPLE_ANSWERS = {
    "full_name": [{"kind": "udf", "udf": "fullName", "args": ["first_name", "last_name"]}],
    "email_address": [{"kind": "udf", "udf": "cleanEmail", "args": ["cust_email_01"]}],
    "date_of_birth": [
        {"kind": "sql", "sql": "CAST(dob AS DATE)"},
        {"kind": "sql", "sql": "COALESCE(SAFE.PARSE_DATE('%Y-%m-%d', dob), SAFE.PARSE_DATE('%d/%m/%Y', dob))"},
    ],
    "weight": [{"kind": "sql", "sql": "CAST(ROUND(weight_kg) AS INT64)"}],
}


@pytest.fixture
def fake_llm(monkeypatch):
    """Install a FakeLLM; call the returned factory with answers (defaults to SAMPLE_ANSWERS)."""
    created = {}

    def install(answers: dict | None = None) -> FakeLLM:
        llm = FakeLLM(answers if answers is not None else SAMPLE_ANSWERS)
        created["llm"] = llm
        monkeypatch.setattr("app.llm.client.get_client", lambda: llm)
        return llm

    return install


@pytest.fixture
def empty_cache():
    with SessionLocal() as db:
        db.query(LlmCacheEntry).delete()
        db.commit()


@pytest.fixture
def sample_inputs() -> dict:
    return {
        "source": sample_text("source_schema.md"),
        "target": sample_text("target_schema.md"),
        "sttm_csv": sample_bytes("sttm.csv"),
        "repo": sample_text("folder_structure.md"),
        "functions": sample_text("functions.js"),
        "env": sample_text("env_vars.js"),
    }


def pytest_sessionfinish(session, exitstatus):
    from app.warehouse import reset_warehouse
    reset_warehouse()
    shutil.rmtree(_TMP, ignore_errors=True)

"""LLM client behaviour (HTTP mocked) and the translator's guard rails."""
import json

import httpx
import pytest
from conftest import sample_text

from app.inputs.schema import parse_schema_md
from app.llm import client as client_mod
from app.llm.client import GroqClient, LlmError, list_price_usd
from app.llm.translator import Translator, _rows_mentioned

SRC = parse_schema_md(sample_text("source_schema.md"))
CATALOG = [
    {"name": "cleanEmail", "kind": "column", "arity": 1, "params": [{"name": "col", "default": None}],
     "example": "LOWER(TRIM(col))", "description": ""},
    {"name": "safeParseDate", "kind": "column", "arity": 1,
     "params": [{"name": "col", "default": None}, {"name": "format", "default": '"%Y-%m-%d"'}],
     "example": "SAFE.PARSE_DATE('%Y-%m-%d', col)", "description": ""},
    {"name": "columnList", "kind": "table", "arity": 1, "params": [{"name": "params", "default": None}],
     "example": None, "description": ""},
]


def _ok(content: dict, **usage) -> httpx.Response:
    return httpx.Response(200, json={
        "choices": [{"message": {"content": json.dumps(content)}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 40,
                  "completion_tokens_details": {"reasoning_tokens": 15}, **usage}})


@pytest.fixture
def http(monkeypatch):
    """Queue fake HTTP responses for httpx.post; records request bodies."""
    queue, sent = [], []

    def fake_post(url, json=None, headers=None, timeout=None):
        sent.append(json)
        return queue.pop(0)

    monkeypatch.setattr(client_mod.httpx, "post", fake_post)
    monkeypatch.setattr(client_mod.time, "sleep", lambda s: sent.append({"slept": s}))
    return queue, sent


def _client():
    return GroqClient("k", "openai/gpt-oss-120b", "https://api.groq.com/openai/v1", 10, "low")


def test_request_is_tuned_for_latency_and_parses_usage(http):
    queue, sent = http
    queue.append(_ok({"mappings": []}))
    reply, usage = _client().complete_json("sys", "user", {"type": "object"}, "x", 500)
    body = sent[0]
    assert body["reasoning_effort"] == "low" and body["include_reasoning"] is False
    assert body["response_format"]["type"] == "json_schema" and body["response_format"]["json_schema"]["strict"]
    assert reply == {"mappings": []}
    assert usage["promptTokens"] == 100 and usage["reasoningTokens"] == 15


def test_429_waits_for_retry_after_then_succeeds(http):
    queue, sent = http
    queue += [httpx.Response(429, headers={"retry-after": "7"}, text="slow down"), _ok({"mappings": []})]
    _client().complete_json("s", "u", {}, "x", 100)
    assert {"slept": 7.0} in sent


def test_strict_mode_falls_back_to_json_mode(http):
    queue, sent = http
    queue += [httpx.Response(400, text='{"error": "response_format json_schema not supported"}'),
              _ok({"mappings": []})]
    _client().complete_json("s", "u", {}, "x", 100)
    assert sent[-1]["response_format"] == {"type": "json_object"}


def test_bad_key_gives_a_readable_error(http):
    queue, _ = http
    queue.append(httpx.Response(401, text="invalid api key"))
    with pytest.raises(LlmError, match="GROQ_API_KEY"):
        _client().complete_json("s", "u", {}, "x", 100)


def test_list_price_counts_cached_tokens_at_the_cached_rate():
    usage = {"promptTokens": 1_000_000, "cachedTokens": 500_000, "completionTokens": 1_000_000}
    assert list_price_usd(usage) == pytest.approx(0.5 * 0.15 + 0.5 * 0.075 + 0.60)


class _Scripted:
    model = "fake"

    def __init__(self, mappings):
        self.mappings = mappings

    def complete_json(self, *a, **k):
        return {"mappings": self.mappings}, {"calls": 1, "promptTokens": 10, "completionTokens": 5,
                                             "cachedTokens": 0, "reasoningTokens": 0, "latencyMs": 1}


def _decision(row, target, source):
    return {"row": row, "target_field": target, "target_type": "STRING", "source_field": source,
            "source_type": "STRING", "rule": "r", "sql_logic": "", "lookup": "", "default": "", "sample": "",
            "method": "llm", "origin": "rule", "udf": None, "sql": None, "status": "needs_llm",
            "error": None, "attempts": 0, "rationale": ""}


def _translator(mappings):
    return Translator(_Scripted(mappings), source=SRC, catalog=CATALOG, env_values={"gold_dataset": "analytics"},
                      functions_name="functions", env_name="env_vars", on_usage=lambda u, n: None,
                      on_event=lambda k, t: None)


def test_guard_rails_on_llm_answers(empty_cache):
    ds = [_decision(i, f"t{i}", "cust_email_01") for i in range(1, 8)]
    _translator([
        {"row": 1, "kind": "udf", "udf": "cleanEmail", "args": ["cust_email_01"], "sql": None, "rationale": "ok"},
        {"row": 2, "kind": "udf", "udf": "madeUpUdf", "args": ["x"], "sql": None, "rationale": ""},
        {"row": 3, "kind": "udf", "udf": "cleanEmail", "args": ["a", "b"], "sql": None, "rationale": ""},
        {"row": 4, "kind": "udf", "udf": "columnList", "args": ["x"], "sql": None, "rationale": ""},
        {"row": 5, "kind": "sql", "udf": None, "args": [], "sql": '${ref("secrets")}', "rationale": ""},
        {"row": 6, "kind": "sql", "udf": None, "args": [],
         "sql": "CONCAT(${functions.cleanEmail(\"cust_email_01\")}, '@${env_vars.gold_dataset}')", "rationale": ""},
        {"row": 6, "kind": "sql", "udf": None, "args": [], "sql": "duplicate ignored", "rationale": ""},
    ]).translate(ds)
    status = {d["row"]: (d["status"], d["error"] or "") for d in ds}
    assert status[1][0] == "pending" and ds[0]["udf"] == {"name": "cleanEmail", "args": ["cust_email_01"]}
    assert "not a column-level UDF" in status[2][1]
    assert "takes 1–1 argument" in status[3][1]
    assert "not a column-level UDF" in status[4][1]           # table-level helpers are off-limits
    assert "templates are allowed" in status[5][1]           # no arbitrary JS / refs from the LLM
    assert status[6][0] == "pending"                         # UDF + env var inside SQL is fine
    assert status[7] == ("failed", "LLM returned no mapping for this row")


def test_cache_key_changes_with_what_the_answer_depends_on():
    t = _translator([])
    a, b = _decision(1, "t", "cust_email_01"), _decision(1, "t", "cust_email_01")
    assert t.cache_key(a) == t.cache_key(b)
    b["rule"] = "a different rule"
    assert t.cache_key(a) != t.cache_key(b)


def test_feedback_scope_matches_named_columns_and_row_numbers():
    ds = [_decision(3, "full_name", "first_name"), _decision(4, "email_address", "cust_email_01"),
          _decision(5, "date_of_birth", "dob")]
    assert [d["row"] for d in _rows_mentioned("email_address must keep the + alias", ds)] == [4]
    assert [d["row"] for d in _rows_mentioned("Row 5 is wrong, and so is row #3", ds)] == [3, 5]
    assert _rows_mentioned("everything looks off", ds) == []


def test_chunks_respect_the_token_budget(monkeypatch):
    monkeypatch.setattr("app.config.settings.llm_rows_per_call", 2)
    t = _translator([])
    chunks = t._chunks([_decision(i, f"t{i}", "dob") for i in range(5)], lambda ctx, rows: ctx)
    assert [len(c) for c in chunks] == [2, 2, 1]

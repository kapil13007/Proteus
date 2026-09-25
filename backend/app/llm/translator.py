"""Translator: turns "needs the LLM" rows into expressions.

  1. Cache first. Answers are keyed by everything they depend on (the row, the
     source columns, the UDF catalog, the model, the prompt version) and are only
     stored after they pass verification, so re-running an unchanged mapping sheet
     costs zero tokens and never replays a bad answer.
  2. Batched calls. All uncached rows go out together, split only to stay well
     inside the free tier's 8K tokens/minute.
  3. Guard rails on the reply. A UDF answer must name a real column-level UDF
     with the right number of arguments; a SQL answer may only use ${...} for
     the UDF library or env vars. Anything else is rejected before it runs.
"""
import hashlib
import json
import re
import time
from typing import Callable

from app.config import settings
from app.database import LlmCacheEntry, SessionLocal
from app.llm import prompts
from app.llm.client import GroqClient, LlmError

_PROMPT_CHAR_BUDGET = 12_000  # ~3.5K tokens: two calls fit in one free-tier minute
_TEMPLATE = re.compile(r"\$\{(.*?)\}", re.DOTALL)


class Translator:
    def __init__(self, client: GroqClient | None, *, source, catalog: list[dict], env_values: dict,
                 functions_name: str, env_name: str | None, on_usage: Callable[[dict, int], None],
                 on_event: Callable[[str, str], None]):
        self.client = client
        self.udfs = {u["name"]: u for u in catalog if u["kind"] == "column"}
        self.env_values = env_values if env_name else {}
        self.env_name = env_name
        self.functions_name = functions_name
        self.on_usage = on_usage
        self.on_event = on_event
        columns = [(c.name, c.type, c.nullable) for c in source.columns.values()]
        self.context = prompts.context_block(source.table, columns, catalog, self.env_values,
                                             functions_name, env_name)
        model = client.model if client else settings.groq_model
        self._fingerprint = json.dumps({
            "prompt": prompts.PROMPT_VERSION, "model": model, "columns": columns,
            "udfs": sorted((u["name"], u["example"]) for u in self.udfs.values()),
            "env": env_values, "library": functions_name,
        }, sort_keys=True)

    # -- cache -------------------------------------------------------------------
    def cache_key(self, d: dict) -> str:
        row = {k: d.get(k) for k in ("source_field", "source_type", "target_field", "target_type",
                                     "rule", "lookup", "sql_logic")}
        payload = self._fingerprint + json.dumps(row, sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()

    def _from_cache(self, decisions: list[dict]) -> list[dict]:
        """Apply cached answers; return the decisions that still need the LLM."""
        if not settings.llm_cache or not decisions:
            return decisions
        keys = {d["row"]: self.cache_key(d) for d in decisions}
        remaining = []
        with SessionLocal() as db:
            hits = {e.key: e for e in db.query(LlmCacheEntry).filter(LlmCacheEntry.key.in_(keys.values()))}
            for d in decisions:
                entry = hits.get(keys[d["row"]])
                if entry is None:
                    remaining.append(d)
                    continue
                self._apply(d, entry.value, origin="cache")
                entry.hits = (entry.hits or 0) + 1
            db.commit()
        return remaining

    def store_verified(self, decisions: list[dict]) -> int:
        fresh = [d for d in decisions if d["method"] == "llm" and d["origin"] == "llm" and d["status"] == "ok"]
        if not settings.llm_cache or not fresh:
            return 0
        now = int(time.time() * 1000)
        with SessionLocal() as db:
            for d in fresh:
                value = {"kind": "udf" if d["udf"] else "sql",
                         "udf": d["udf"]["name"] if d["udf"] else None,
                         "args": d["udf"]["args"] if d["udf"] else [],
                         "sql": d["sql"], "rationale": d["rationale"]}
                db.merge(LlmCacheEntry(key=self.cache_key(d), value=value,
                                       model=self.client.model if self.client else "", created_at=now, hits=0))
            db.commit()
        return len(fresh)

    # -- public entry points ------------------------------------------------------------
    def translate(self, decisions: list[dict]) -> None:
        remaining = self._from_cache(decisions)
        cached = len(decisions) - len(remaining)
        if cached:
            self.on_event("tool_result", f"llm cache: {cached} row(s) answered from earlier verified runs — 0 tokens")
        self._call(remaining, prompts.translate_prompt, "translate")

    def repair(self, decisions: list[dict]) -> None:
        self._call(decisions, prompts.repair_prompt, "repair")

    def revise(self, decisions: list[dict], feedback: str) -> list[dict]:
        if self.client is None:
            raise LlmError("No LLM configured (GROQ_API_KEY is empty) — use a per-row override instead")
        scope = _rows_mentioned(feedback, decisions) or decisions
        self.on_event("tool_call", f"llm.revise({len(scope)} row(s) in scope) — reviewer feedback")
        reply, usage = self.client.complete_json(
            prompts.SYSTEM, prompts.revise_prompt(self.context, scope, feedback),
            prompts.MAPPING_SCHEMA, "sttm_mappings", _max_tokens(len(scope)))
        self.on_usage(usage, len(scope))
        by_row = {d["row"]: d for d in scope}
        changed = []
        for m in reply.get("mappings") or []:
            d = by_row.get(m.get("row"))
            if d is None or d in changed:
                continue
            self._apply(d, m, origin="llm")
            d["method"] = "llm"
            d["repaired"] = False
            d["rationale"] = f"Revised for reviewer feedback: {d['rationale']}"
            changed.append(d)
        self.on_event("tool_result", f"{len(changed)} row(s) changed · {usage['promptTokens'] + usage['completionTokens']} tokens")
        return changed

    # -- internals ----------------------------------------------------------------------
    def _call(self, decisions: list[dict], build: Callable[[str, list[dict]], str], purpose: str) -> None:
        if not decisions:
            return
        if self.client is None:
            for d in decisions:
                _fail(d, "No LLM configured (GROQ_API_KEY is empty) — add a per-row override in review")
            self.on_event("tool_error", f"{len(decisions)} row(s) need the LLM but GROQ_API_KEY is not set")
            return
        for chunk in self._chunks(decisions, build):
            self.on_event("tool_call", f"llm.{purpose}(rows {', '.join(str(d['row']) for d in chunk)}) → {self.client.model}")
            try:
                reply, usage = self.client.complete_json(
                    prompts.SYSTEM, build(self.context, chunk), prompts.MAPPING_SCHEMA,
                    "sttm_mappings", _max_tokens(len(chunk)))
            except LlmError as e:
                for d in chunk:
                    _fail(d, f"LLM call failed: {e}")
                self.on_event("tool_error", f"LLM call failed: {e}")
                continue
            self.on_usage(usage, len(chunk))
            by_row: dict = {}
            for m in reply.get("mappings") or []:
                by_row.setdefault(m.get("row"), m)
            for d in chunk:
                m = by_row.get(d["row"])
                if m is None:
                    _fail(d, "LLM returned no mapping for this row")
                    continue
                was_logic = d["method"] == "sql_logic"
                self._apply(d, m, origin="llm")
                if was_logic:
                    d["repaired"] = True
                    d["rationale"] = f"STTM sql_logic failed verification; LLM rewrite: {d['rationale']}"
            tokens = usage["promptTokens"] + usage["completionTokens"]
            self.on_event("tool_result", f"{len(chunk)} mapping(s) · {tokens} tokens · {usage['latencyMs']} ms")

    def _chunks(self, decisions: list[dict], build) -> list[list[dict]]:
        chunks, current = [], []
        for d in decisions:
            candidate = current + [d]
            too_big = len(build(self.context, candidate)) > _PROMPT_CHAR_BUDGET
            if current and (len(candidate) > settings.llm_rows_per_call or too_big):
                chunks.append(current)
                current = [d]
            else:
                current = candidate
        if current:
            chunks.append(current)
        return chunks

    def _apply(self, d: dict, m: dict, origin: str) -> None:
        if origin == "llm":
            d["attempts"] = d.get("attempts", 0) + 1
        d.update(origin=origin, error=None, status="pending")
        rationale = str(m.get("rationale") or "").strip()[:240]
        d["rationale"] = rationale + (" (cached)" if origin == "cache" else "")
        if m.get("kind") == "udf":
            name, args = m.get("udf") or "", [str(a) for a in (m.get("args") or [])]
            u = self.udfs.get(name)
            if u is None:
                return _fail(d, f'LLM chose "{name}", which is not a column-level UDF in {self.functions_name}.js')
            if not u["arity"] <= len(args) <= len(u["params"]):
                return _fail(d, f"{name}() takes {u['arity']}–{len(u['params'])} argument(s); the LLM passed {len(args)}")
            d.update(udf={"name": name, "args": args}, sql=None)
            return None
        sql = str(m.get("sql") or "").strip().rstrip(";").strip()
        if not sql:
            return _fail(d, "LLM returned an empty expression")
        for body in _TEMPLATE.findall(sql):
            if not _allowed_template(body, self.functions_name, self.udfs, self.env_name, self.env_values):
                d.update(sql=sql, udf=None)
                return _fail(d, f"only ${{{self.functions_name}.<udf>(...)}} and environment-variable templates "
                                f"are allowed in SQL, got ${{{body.strip()}}}")
        d.update(sql=sql, udf=None)
        return None


def _fail(d: dict, message: str) -> None:
    d.update(status="failed", error=message)


def _allowed_template(body: str, functions_name: str, udfs: dict, env_name: str | None, env_values: dict) -> bool:
    m = re.fullmatch(r"\s*([A-Za-z_$][\w$]*)\.([A-Za-z_$][\w$]*)\s*(\(.*\))?\s*", body, re.DOTALL)
    if not m:
        return False
    lib, member, call = m.groups()
    if lib == functions_name:
        return member in udfs and call is not None
    return env_name is not None and lib == env_name and member in env_values and call is None


def _max_tokens(rows: int) -> int:
    return min(4096, 600 + 160 * rows)  # reasoning headroom + ~60-100 tokens per mapping


def _rows_mentioned(feedback: str, decisions: list[dict]) -> list[dict]:
    """Rows the feedback names (by column or 'row N'), so the revise call stays small."""
    text = feedback.lower()
    numbers = {int(n) for n in re.findall(r"\brow\s*#?\s*(\d+)", text)}
    hits = []
    for d in decisions:
        names = [n.lower() for n in (d["target_field"], d["source_field"]) if n]
        if d["row"] in numbers or any(re.search(rf"\b{re.escape(n)}\b", text) for n in names):
            hits.append(d)
    return hits

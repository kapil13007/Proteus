"""Prompts. Static instructions first, variable data last.

The system prompt never changes between calls, so a provider-side prompt cache
can reuse it. The model sees only what it needs to translate the rows at hand:
source columns (name + type), the UDF catalog (one line per function) and the
rows as compact JSON lines — never whole files. The answer is small structured
JSON, not a .sqlx file: output tokens are the slow and expensive ones.
"""
import json

# Part of the LLM cache key: changing the prompts invalidates cached answers.
PROMPT_VERSION = "2026-09-23.3"

SYSTEM = """You are a senior analytics engineer on a BigQuery + Dataform team. You translate rows of a \
source-to-target mapping (STTM) sheet into column expressions for the process step of a Dataform pipeline.

For each row, return one mapping:
- kind "udf": call one of the team's UDFs. Set "udf" to its name and "args" to its arguments as SQL text \
(usually source column names). Set "sql" to null.
- kind "sql": write one BigQuery Standard SQL scalar expression over the source columns. Set "udf" to null \
and "args" to [].

Rules:
1. Prefer the team's UDFs: they are reviewed, cost-optimised logic. Never re-implement what a UDF already \
does. When the rule needs a UDF combined with other SQL, or applied more than once, use kind "sql" and call \
it inline as ${LIBRARY.name("arg", ...)}, where LIBRARY is the UDF library name given below. Example with \
hypothetical UDFs parseTs(col, fmt) and toCents(col): \
"COALESCE(${LIBRARY.parseTs(\\"ts\\")}, ${LIBRARY.parseTs(\\"ts\\", \\"%d/%m/%Y %H:%M\\")})".
2. Reference only the listed source columns. No SELECT, FROM, subqueries, aliases or comments.
3. The pipeline casts your result to the target type, so return a value that converts cleanly.
4. Source data is dirty. When parsing text use SAFE_CAST or SAFE.-prefixed functions, so bad values become \
NULL instead of failing the load.
5. Ignore the row's default value; the pipeline wraps your expression in COALESCE(expr, default).
6. rationale: one sentence of at most 15 words saying why this implementation."""

MAPPING_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["mappings"],
    "properties": {
        "mappings": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["row", "kind", "udf", "args", "sql", "rationale"],
                "properties": {
                    "row": {"type": "integer"},
                    "kind": {"type": "string", "enum": ["udf", "sql"]},
                    "udf": {"type": ["string", "null"]},
                    "args": {"type": "array", "items": {"type": "string"}},
                    "sql": {"type": ["string", "null"]},
                    "rationale": {"type": "string"},
                },
            },
        }
    },
}


def context_block(source_table: str, columns: list[tuple[str, str, bool]], catalog: list[dict],
                  env_values: dict, functions_name: str, env_name: str | None) -> str:
    lines = [f"Source table {source_table} (column type):"]
    lines += [f"{name} {typ}{'' if nullable else ' NOT NULL'}" for name, typ, nullable in columns]
    udfs = [u for u in catalog if u["kind"] == "column"]
    if udfs:
        lines.append(f"\nTeam UDFs, LIBRARY = {functions_name} (name(params) -> SQL it expands to -- description):")
        for u in udfs:
            params = ", ".join(p["name"] + (f"={p['default']}" if p["default"] else "") for p in u["params"])
            desc = f" -- {u['description']}" if u.get("description") else ""
            lines.append(f"{u['name']}({params}) -> {u['example']}{desc}")
    else:
        lines.append("\nTeam UDFs: none provided.")
    if env_values and env_name:
        pairs = ", ".join(f"{k}={json.dumps(v)}" for k, v in env_values.items())
        lines.append(f"\nEnvironment variables (usable in sql as ${{{env_name}.NAME}}): {pairs}")
    return "\n".join(lines)


def _row_payload(d: dict) -> dict:
    p = {"row": d["row"], "source": d["source_field"] or None, "source_type": d["source_type"] or None,
         "target": d["target_field"], "target_type": d["target_type"], "rule": d["rule"]}
    for key in ("lookup", "sample"):
        if d.get(key):
            p[key] = d[key]
    if d.get("sql_logic"):
        p["sttm_sql_logic"] = d["sql_logic"]
    return p


def translate_prompt(context: str, decisions: list[dict]) -> str:
    rows = "\n".join(json.dumps(_row_payload(d), ensure_ascii=False) for d in decisions)
    return f"{context}\n\nRows to translate (one mapping per row):\n{rows}"


def repair_prompt(context: str, decisions: list[dict]) -> str:
    rows = []
    for d in decisions:
        p = _row_payload(d)
        p["previous"] = d.get("template") or d.get("sql") or ""
        p["error"] = (d.get("error") or "")[:400]
        rows.append(json.dumps(p, ensure_ascii=False))
    return (f"{context}\n\nThese expressions failed verification against sampled source rows. "
            "Return a corrected mapping for every row, keeping the intent of the rule:\n" + "\n".join(rows))


def revise_prompt(context: str, decisions: list[dict], feedback: str) -> str:
    rows = [json.dumps({"row": d["row"], "target": d["target_field"], "target_type": d["target_type"],
                        "rule": d["rule"], "current": d.get("template") or d.get("sql") or ""},
                       ensure_ascii=False) for d in decisions]
    return (f"{context}\n\nA reviewer asked for changes.\nReviewer feedback: {json.dumps(feedback)}\n\n"
            "Current mappings:\n" + "\n".join(rows) +
            "\n\nReturn mappings ONLY for the rows the feedback asks to change (an empty list if none).")

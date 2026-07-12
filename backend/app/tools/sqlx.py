"""Convert the generated Dataform-style .sqlx into SQL runnable on local Postgres.

The .sqlx body is a single SELECT. Locally we:
  1. strip the config { ... } block (brace-counted, handles nesting)
  2. resolve ${ref("table")} -> raw.table
  3. wrap into INSERT INTO analytics.target (cols...) <select>
"""
import re

from app.config import settings


def strip_config_block(sqlx: str) -> str:
    m = re.search(r"config\s*\{", sqlx)
    if not m:
        return sqlx.strip()
    depth, i = 0, m.start()
    start = m.start()
    while i < len(sqlx):
        if sqlx[i] == "{":
            depth += 1
        elif sqlx[i] == "}":
            depth -= 1
            if depth == 0:
                return (sqlx[:start] + sqlx[i + 1:]).strip()
        i += 1
    return sqlx.strip()  # unbalanced braces; let the dry-run surface the error


def resolve_refs(sql: str) -> str:
    return re.sub(
        r"\$\{\s*ref\(\s*['\"]([\w.]+)['\"]\s*\)\s*\}",
        lambda m: m.group(1) if "." in m.group(1) else f"{settings.source_schema}.{m.group(1)}",
        sql,
    )


def extract_select(sqlx: str) -> str:
    sql = strip_config_block(sqlx)
    # drop js {} blocks and pre-select comments Dataform allows
    sql = re.sub(r"js\s*\{[^}]*\}", "", sql)
    sql = resolve_refs(sql).strip().rstrip(";")
    idx = re.search(r"\bselect\b", sql, flags=re.IGNORECASE)
    if not idx:
        raise ValueError("Generated .sqlx contains no SELECT statement")
    return sql[idx.start():]


def build_insert(sqlx: str, target_table: str, target_fields: list[str]) -> str:
    select_sql = extract_select(sqlx)
    cols = ", ".join(f'"{c}"' for c in target_fields)
    return f"INSERT INTO {target_table} ({cols})\n{select_sql}"


def extract_sqlx_from_llm(text: str) -> str:
    """LLM replies with a fenced block; take the first one, else the raw text."""
    m = re.search(r"```(?:sqlx|sql)?\s*\n(.*?)```", text, flags=re.DOTALL)
    return (m.group(1) if m else text).strip()

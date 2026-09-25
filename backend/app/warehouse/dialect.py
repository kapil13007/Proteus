"""SQL dialect handling with sqlglot: static checks and BigQuery -> local translation.

Generated code is written in the real warehouse's dialect (BigQuery). The local
sandbox is DuckDB, so SQL is transpiled before it runs. sqlglot covers almost
all of it; the few shims below handle BigQuery constructs it leaves invalid for
DuckDB. Anything else that fails to transpile is reported like any other error,
so the repair loop can pick an equivalent formulation.
"""
import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

from app.config import settings

SOURCE_DIALECT = settings.target_dialect
LOCAL_DIALECT = "duckdb"

_FORBIDDEN = (exp.Query, exp.DDL, exp.DML, exp.Command, exp.Drop, exp.Star,
              exp.Parameter, exp.Placeholder)


class SqlError(Exception):
    pass


def _first_line(e: Exception) -> str:
    return str(e).strip().splitlines()[0] if str(e).strip() else type(e).__name__


def parse_expression(sql: str) -> exp.Expression:
    """Parse one scalar column expression, rejecting anything that isn't one."""
    text = (sql or "").strip().rstrip(";").strip()
    if not text:
        raise SqlError("empty expression")
    try:
        tree = sqlglot.parse_one(text, read=SOURCE_DIALECT)
    except ParseError as e:
        raise SqlError(f"syntax error: {_first_line(e)}") from e
    if isinstance(tree, exp.Alias):  # tolerate "expr AS name" — the alias is added by the pipeline
        tree = tree.this
    bad = tree if isinstance(tree, _FORBIDDEN) else tree.find(*_FORBIDDEN)
    if bad is not None:
        kind = "a subquery" if isinstance(bad, exp.Query) else f"'{bad.key.upper()}'"
        raise SqlError(f"a column expression cannot contain {kind}; use a single scalar expression")
    return tree


def referenced_columns(tree: exp.Expression) -> list[str]:
    seen: list[str] = []
    for col in tree.find_all(exp.Column):
        if col.name and col.name not in seen:
            seen.append(col.name)
    return seen


def normalize(sql: str) -> str | None:
    """Canonical text for equivalence checks (whitespace/case-insensitive), or None if unparsable."""
    try:
        return parse_expression(sql).sql(dialect=SOURCE_DIALECT, normalize=True, comments=False)
    except SqlError:
        return None


def _shim(node: exp.Expression) -> exp.Expression:
    if isinstance(node, exp.SafeFunc):  # SAFE.PARSE_DATE(...) -> TRY(...): same "NULL on error" semantics
        return exp.Anonymous(this="TRY", expressions=[node.this])
    if isinstance(node, exp.CurrentDatetime):
        return exp.cast(exp.CurrentTimestamp(), "TIMESTAMP")
    return node


def expression_to_local(sql: str) -> str:
    tree = parse_expression(sql)
    try:
        return tree.transform(_shim).sql(dialect=LOCAL_DIALECT)
    except Exception as e:  # noqa: BLE001 — unsupported construct for the local engine
        raise SqlError(f"cannot run locally: {_first_line(e)}") from e


def statement_to_local(sql: str) -> str:
    """Transpile a full SELECT. Exactly one statement is allowed — generated SQL never gets to
    smuggle a second statement past the sandbox."""
    try:
        statements = [s for s in sqlglot.parse(sql, read=SOURCE_DIALECT) if s is not None]
    except ParseError as e:
        raise SqlError(f"syntax error: {_first_line(e)}") from e
    if len(statements) != 1 or not isinstance(statements[0], exp.Query):
        raise SqlError("expected exactly one SELECT statement")
    try:
        return statements[0].transform(_shim).sql(dialect=LOCAL_DIALECT, pretty=True)
    except Exception as e:  # noqa: BLE001
        raise SqlError(f"cannot run locally: {_first_line(e)}") from e


def quote_ident(name: str) -> str:
    """BigQuery identifier, backtick-quoted only when needed."""
    if name.replace("_", "a").isalnum() and not name[0].isdigit():
        return name
    return "`" + name.replace("`", "\\`") + "`"


def sql_literal(value: str) -> str:
    return "'" + str(value).replace("\\", "\\\\").replace("'", "\\'") + "'"

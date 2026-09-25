"""Local warehouse: an embedded DuckDB file.

Why DuckDB: it is free, in-process (no server, no network hop — dry runs take
milliseconds), columnar like BigQuery, and supports CREATE OR REPLACE TABLE AS
SELECT, the same full-refresh idiom BigQuery uses. sqlglot translates the
generated BigQuery SQL into DuckDB SQL before anything runs here.

Concurrency: one DuckDB connection per process; every thread works on its own
cursor. Verification sandboxes are TEMP views, which DuckDB scopes to a single
cursor, so concurrent runs never see each other's samples.
"""
import threading
from contextlib import contextmanager
from pathlib import Path

import duckdb

from app.inputs.schema import TableSchema
from app.inputs.types import compatible, duckdb_type, family

SANDBOX_VIEW = "__mapflow_source"     # sampled rows + the STTM's own sample row (per-column probes)
SANDBOX_ROWS_VIEW = "__mapflow_rows"  # sampled rows only (whole-pipeline preview)

# BigQuery logical storage size per value (bytes). NULLs cost 0.
# STRING/BYTES are 2 bytes + payload; see BigQuery "data size calculation".
_FIXED_BYTES = {"int": 8, "float": 8, "numeric": 16, "bool": 1, "date": 8,
                "datetime": 8, "timestamp": 8, "time": 8}


def _q(ident: str) -> str:
    return '"' + ident.replace('"', '""') + '"'


def _qt(table: str) -> str:
    return ".".join(_q(p) for p in table.split("."))


def _lit(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _first_line(e: Exception) -> str:
    text = str(e).strip()
    return text.splitlines()[0] if text else type(e).__name__


class LocalSqlError(Exception):
    pass


class DuckSandbox:
    def __init__(self, cur: duckdb.DuckDBPyConnection):
        self._cur = cur

    def describe(self, sql: str) -> list[tuple[str, str]]:
        try:
            return [(r[0], r[1]) for r in self._cur.execute(f"DESCRIBE {sql}").fetchall()]
        except duckdb.Error as e:
            raise LocalSqlError(_first_line(e)) from e

    def rows(self, sql: str, limit: int | None = None) -> tuple[list[str], list[tuple]]:
        try:
            res = self._cur.execute(sql if limit is None else f"SELECT * FROM ({sql}) LIMIT {int(limit)}")
            cols = [d[0] for d in res.description]
            return cols, res.fetchall()
        except duckdb.Error as e:
            raise LocalSqlError(_first_line(e)) from e


class DuckDBWarehouse:
    engine = "duckdb"
    dialect = "duckdb"

    def __init__(self, path: str):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._con = duckdb.connect(path)
        # GLOBAL: every thread works on its own cursor, and plain SET is per-connection.
        self._con.execute("SET GLOBAL TimeZone = 'UTC'")
        self._write_lock = threading.Lock()

    def lock_down(self) -> None:
        """No file reads, extension installs or network from generated SQL. Irreversible."""
        self._con.execute("SET enable_external_access = false")

    def close(self) -> None:
        self._con.close()

    def _cursor(self) -> duckdb.DuckDBPyConnection:
        return self._con.cursor()

    def execute_script(self, sql: str) -> None:
        with self._write_lock:
            self._cursor().execute(sql)

    # -- catalog --------------------------------------------------------------
    def table_columns(self, table: str) -> dict[str, str] | None:
        schema, name = table.split(".", 1)
        rows = self._cursor().execute(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = ? AND table_name = ? ORDER BY ordinal_position",
            [schema, name]).fetchall()
        return {r[0]: r[1] for r in rows} or None

    def list_tables(self) -> list[str]:
        rows = self._cursor().execute(
            "SELECT table_schema || '.' || table_name FROM information_schema.tables "
            "WHERE table_schema NOT IN ('information_schema', 'pg_catalog') ORDER BY 1").fetchall()
        return [r[0] for r in rows]

    def row_count(self, table: str) -> int:
        return self._cursor().execute(f"SELECT COUNT(*) FROM {_qt(table)}").fetchone()[0]

    # -- bootstrap a missing source from its contract --------------------------
    def create_from_contract(self, schema: TableSchema, rows: list[dict]) -> None:
        cols = ", ".join(f"{_q(c.name)} {duckdb_type(c.type)}" for c in schema.columns.values())
        with self._write_lock:
            cur = self._cursor()
            cur.execute(f"CREATE SCHEMA IF NOT EXISTS {_q(schema.dataset)}")
            cur.execute(f"CREATE TABLE {_qt(schema.table)} ({cols})")
            for row in rows:
                values = ", ".join(
                    f"TRY_CAST({_lit(row[c.name])} AS {duckdb_type(c.type)})"
                    if row.get(c.name) not in (None, "") else "NULL"
                    for c in schema.columns.values())
                cur.execute(f"INSERT INTO {_qt(schema.table)} VALUES ({values})")

    # -- verification sandbox ----------------------------------------------------
    @contextmanager
    def sandbox(self, source_table: str, extra_row: dict | None, limit: int, types: dict[str, str]):
        """TEMP views (scoped to this cursor) over up to `limit` source rows; the probe view also
        starts with the STTM's own sample row, so examples show the analyst's sample first."""
        cur = self._cursor()
        probe = f"SELECT * FROM {SANDBOX_ROWS_VIEW}"
        if extra_row:
            cols = ", ".join(
                (f"TRY_CAST({_lit(extra_row[c])} AS {t})" if extra_row.get(c) not in (None, "")
                 else f"CAST(NULL AS {t})") + f" AS {_q(c)}"
                for c, t in types.items())
            probe = f"SELECT {cols} UNION ALL BY NAME ({probe})"
        try:
            cur.execute(f"CREATE OR REPLACE TEMP VIEW {SANDBOX_ROWS_VIEW} AS "
                        f"SELECT * FROM {_qt(source_table)} LIMIT {int(limit)}")
            cur.execute(f"CREATE OR REPLACE TEMP VIEW {SANDBOX_VIEW} AS {probe}")
            yield DuckSandbox(cur)
        finally:
            cur.close()

    # -- execution -----------------------------------------------------------------
    def replace_table(self, select_sql: str, target_table: str) -> int:
        schema = target_table.split(".", 1)[0]
        with self._write_lock:
            cur = self._cursor()
            try:
                cur.execute(f"CREATE SCHEMA IF NOT EXISTS {_q(schema)}")
                cur.execute(f"CREATE OR REPLACE TABLE {_qt(target_table)} AS {select_sql}")
            except duckdb.Error as e:
                raise LocalSqlError(_first_line(e)) from e
            return cur.execute(f"SELECT COUNT(*) FROM {_qt(target_table)}").fetchone()[0]

    def audit(self, source_table: str, target: TableSchema) -> dict:
        """The same checks the generated Dataform assertions encode, run locally."""
        cur = self._cursor()
        t = _qt(target.table)
        written = cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        source_rows = self.row_count(source_table)
        checks = [{"name": "row count", "ok": written == source_rows,
                   "detail": f"{written:,} rows written from {source_rows:,} source rows"}]

        null_cols = []
        for col in target.required:
            n = cur.execute(f"SELECT COUNT(*) FROM {t} WHERE {_q(col)} IS NULL").fetchone()[0]
            if n:
                null_cols.append(f"{col} ({n})")
        checks.append({"name": "nonNull", "ok": not null_cols,
                       "detail": ("nulls in " + ", ".join(null_cols)) if null_cols
                       else f"{len(target.required)} required column(s) fully populated"})

        if target.keys:
            key_expr = ", ".join(_q(k) for k in target.keys)
            dupes = cur.execute(
                f"SELECT COUNT(*) FROM (SELECT {key_expr} FROM {t} GROUP BY ALL HAVING COUNT(*) > 1)"
            ).fetchone()[0]
            checks.append({"name": "uniqueKey", "ok": dupes == 0,
                           "detail": f"{dupes} duplicate key(s) on ({', '.join(target.keys)})" if dupes
                           else f"({', '.join(target.keys)}) is unique"})

        actual = self.table_columns(target.table) or {}
        problems = []
        if list(actual) != list(target.columns):
            problems.append("column order/names differ from the contract")
        for name, col in target.columns.items():
            if name in actual and not compatible(family(actual[name]), col.family):
                problems.append(f"{name} is {actual[name]}, contract says {col.type}")
        checks.append({"name": "schema contract", "ok": not problems,
                       "detail": "; ".join(problems) or f"{len(actual)} columns match the target schema"})

        failed = next((c for c in checks if not c["ok"]), None)
        return {
            "rowsWritten": written,
            "sourceRows": source_rows,
            "countsMatch": checks[0]["ok"],
            "nullsCheck": checks[1]["ok"],
            "failedCheck": f'{failed["name"]}: {failed["detail"]}' if failed else None,
            "checks": checks,
        }

    # -- cost model --------------------------------------------------------------------
    def scan_bytes(self, table: str, columns: dict[str, str]) -> dict[str, int]:
        """BigQuery-equivalent logical bytes per column (what an on-demand query is billed on)."""
        if not columns:
            return {}
        parts = []
        for name, col_type in columns.items():
            fam = family(col_type)
            if fam in _FIXED_BYTES:
                parts.append(f"COUNT({_q(name)}) * {_FIXED_BYTES[fam]}")
            else:
                parts.append(f"COALESCE(SUM(2 + strlen(CAST({_q(name)} AS VARCHAR))), 0)")
        values = self._cursor().execute(f"SELECT {', '.join(parts)} FROM {_qt(table)}").fetchone()
        return {name: int(v or 0) for name, v in zip(columns, values)}

"""The warehouse seam.

Everything the pipeline needs from a warehouse, and nothing else. The local
implementation is DuckDB (free, embedded). A BigQuery or Athena adapter would
implement the same methods: `replace_table` is CREATE OR REPLACE TABLE AS SELECT
on BigQuery and delete-prefix + CTAS on Athena, which is why the seam is
"replace a table from a SELECT" rather than TRUNCATE + INSERT.
"""
from contextlib import AbstractContextManager
from typing import Protocol

from app.inputs.schema import TableSchema


class Sandbox(Protocol):
    """A throwaway, per-verification view of sampled source rows."""

    def describe(self, sql: str) -> list[tuple[str, str]]: ...
    def rows(self, sql: str, limit: int | None = None) -> tuple[list[str], list[tuple]]: ...


class Warehouse(Protocol):
    engine: str
    dialect: str  # sqlglot dialect name used for local execution

    def table_columns(self, table: str) -> dict[str, str] | None: ...
    def list_tables(self) -> list[str]: ...
    def create_from_contract(self, schema: TableSchema, rows: list[dict]) -> None: ...
    def sandbox(self, source_table: str, extra_row: dict | None, limit: int,
                types: dict[str, str]) -> AbstractContextManager[Sandbox]: ...
    def replace_table(self, select_sql: str, target_table: str) -> int: ...
    def audit(self, source_table: str, target: TableSchema) -> dict: ...
    def scan_bytes(self, table: str, columns: dict[str, str]) -> dict[str, int]: ...

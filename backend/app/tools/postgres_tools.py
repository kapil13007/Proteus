"""The agent's 'warehouse' tools, backed by local Postgres.

In v2 these four functions swap to BigQuery/Dataform equivalents — the agent
and everything above it stays identical.
"""
import json

from sqlalchemy import text

from app.database import engine


def get_table_schema(qualified: str) -> dict:
    """qualified: 'raw.clinical_patients' -> {table, columns:{name:{type, nullable}}}"""
    schema, table = qualified.split(".", 1)
    q = text(
        """SELECT column_name, data_type, is_nullable
           FROM information_schema.columns
           WHERE table_schema = :s AND table_name = :t
           ORDER BY ordinal_position"""
    )
    with engine.connect() as conn:
        rows = conn.execute(q, {"s": schema, "t": table}).fetchall()
    if not rows:
        raise ValueError(f"Table {qualified} not found in local Postgres")
    return {
        "table": qualified,
        "columns": {r[0]: {"type": r[1].upper(), "nullable": r[2] == "YES"} for r in rows},
    }


def dry_run(insert_sql: str) -> dict:
    """EXPLAIN the INSERT. Returns {success, error?, est_rows?, est_bytes?}."""
    try:
        with engine.connect() as conn:
            res = conn.execute(text("EXPLAIN (FORMAT JSON) " + insert_sql))
            plan = res.fetchone()[0]
            if isinstance(plan, str):
                plan = json.loads(plan)
            node = plan[0]["Plan"]
            # INSERT's top node reports 0 rows; the estimate lives in its child SELECT
            if not node.get("Plan Rows") and node.get("Plans"):
                node = node["Plans"][0]
            est_rows = int(node.get("Plan Rows", 0))
            est_bytes = est_rows * int(node.get("Plan Width", 0))
            return {"success": True, "est_rows": est_rows, "est_bytes": est_bytes}
    except Exception as e:
        msg = str(getattr(e, "orig", e)).strip().split("\n")[0]
        return {"success": False, "error": msg}


def execute_insert(insert_sql: str, target_table: str, full_refresh: bool = True) -> int:
    with engine.begin() as conn:
        if full_refresh:
            conn.execute(text(f"TRUNCATE TABLE {target_table}"))
        result = conn.execute(text(insert_sql))
        return result.rowcount or 0


def audit(source_table: str, target_table: str, required_cols: list[str]) -> dict:
    with engine.connect() as conn:
        src = conn.execute(text(f"SELECT COUNT(*) FROM {source_table}")).scalar() or 0
        tgt = conn.execute(text(f"SELECT COUNT(*) FROM {target_table}")).scalar() or 0
        null_violations = 0
        bad_col = None
        for col in required_cols:
            n = conn.execute(
                text(f'SELECT COUNT(*) FROM {target_table} WHERE "{col}" IS NULL')
            ).scalar() or 0
            if n:
                null_violations += n
                bad_col = bad_col or col
    return {
        "rows_written": tgt,
        "source_rows": src,
        "counts_match": src == tgt,
        "null_violations": null_violations,
        "bad_col": bad_col,
    }

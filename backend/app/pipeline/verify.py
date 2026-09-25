"""Verification: prove the generated code works before a human is asked to approve it.

Per row, cheapest check first:
  1. expand ${...} with the team's real JS (V8)     -> UDF calls resolve, with the right arguments
  2. parse the expression (sqlglot)                 -> syntax, one scalar expression, no subqueries
  3. referenced columns exist in the source         -> no hallucinated columns
  4. transpile BigQuery -> DuckDB                   -> it can run locally
  5. run it over sampled source rows, including the
     final CAST to the target type                  -> runtime errors (bad casts, bad formats)
Each failure is pinned to one STTM row, so a repair only resends the rows that
broke — never the whole file.

Then the rendered files are compiled as a whole (read -> process -> write, as
CTEs) and dry-run on the same sample, which is what the reviewer previews.
"""
import re
from dataclasses import dataclass, field

from app.dataform import CompileError
from app.dataform.compiler import DataformProject, strip_sql_comments
from app.dataform.render import RenderInput, action_names, column_expression, column_template, render_files
from app.inputs.types import LOSSY, duckdb_type, family
from app.mapping import finding
from app.pipeline.context import RunContext
from app.warehouse.dialect import SqlError, expression_to_local, parse_expression, referenced_columns, statement_to_local
from app.warehouse.duckdb_wh import SANDBOX_ROWS_VIEW, SANDBOX_VIEW, DuckDBWarehouse, LocalSqlError

PREVIEW_ROWS = 10


def _examples(cols: list[str], rows: list[tuple]) -> tuple[list[dict], dict | None]:
    """Pick explanatory examples (the STTM sample first, then rows the rule visibly changed) and
    count values the expression silently turned into NULL."""
    def as_example(r):
        return {"in": dict(zip(cols, r[1:])), "out": r[0]}

    lost = [r for r in rows if r[0] is None and any(v is not None for v in r[1:])]
    changed = [r for r in rows[1:] if r[0] is not None and (len(r) != 2 or r[0] != r[1])]
    picked = rows[:1] + lost[:1] + changed
    seen, examples = set(), []
    for r in picked + rows:
        if r not in seen:
            seen.add(r)
            examples.append(as_example(r))
        if len(examples) == 3:
            break
    nulls = None
    if lost:
        samples = sorted({str(r[1]) for r in lost if len(r) > 1 and r[1] is not None})[:3]
        nulls = {"count": len(lost), "of": len(rows), "examples": samples}
    return examples, nulls


@dataclass
class VerifyResult:
    files: list[dict] = field(default_factory=list)
    read_columns: list[str] = field(default_factory=list)
    pipeline_sql: str = ""       # local dialect, reads the physical source table
    preview: dict = field(default_factory=dict)
    scan: dict = field(default_factory=dict)
    findings: list[dict] = field(default_factory=list)
    pipeline_error: str | None = None


def _fail(d: dict, message: str) -> None:
    d.update(status="failed", error=message)


def compile_pipeline(project: DataformProject, files: list[dict], ctx: RunContext, source_ref: str) -> str:
    """read -> process -> write as one SELECT with CTEs (BigQuery inlines the views the same way)."""
    names = action_names(ctx.conventions, ctx.target)
    project.set_refs({ctx.source.name: source_ref, names["read"]: names["read"], names["process"]: names["process"]})
    by_kind = {f["kind"]: f for f in files}
    read = project.compile_file(by_kind["read"]["content"], names["read"])
    process = project.compile_file(by_kind["process"]["content"], names["process"])
    write = project.compile_file(by_kind["write"]["content"], names["write"])

    def body(sql: str) -> str:
        return strip_sql_comments(sql).strip()

    return (f"WITH {read.name} AS (\n{body(read.sql)}\n),\n"
            f"{process.name} AS (\n{body(process.sql)}\n)\n{body(write.sql)}")


def sample_row(decisions: list[dict]) -> dict:
    """The STTM's own sample_data values, as one extra source row (first sample per field wins)."""
    row: dict = {}
    for d in decisions:
        if d["source_field"] and d.get("sample") and d["source_field"] not in row:
            row[d["source_field"]] = d["sample"]
    return row


def verify(ctx: RunContext, project: DataformProject, warehouse: DuckDBWarehouse,
           decisions: list[dict], sample_limit: int) -> VerifyResult:
    result = VerifyResult()
    fn = ctx.functions_name
    live_types = warehouse.table_columns(ctx.source.table) or {}

    # -- 1-4: static checks, one V8 round trip for all rows -------------------------------
    candidates = []
    for d in decisions:
        if d["status"] == "ok":
            d["status"] = "pending"  # re-verify everything each pass; it costs milliseconds
        if d["status"] != "pending":
            continue
        d["template"] = column_template(d, fn)
        d["expression"] = column_expression(d, fn)
        d["udfs_used"] = sorted(set(re.findall(r"\$\{\s*" + re.escape(fn) + r"\.([\w$]+)\s*\(", d["expression"])))
        candidates.append(d)

    local_expr: dict[int, str] = {}
    for d, res in zip(candidates, project.expand([d["expression"] for d in candidates])):
        if not res["ok"]:
            _fail(d, f"template error: {res['error']}")
            continue
        d["compiled"] = res["sql"]
        try:
            cols = referenced_columns(parse_expression(res["sql"]))
            unknown = [c for c in cols if c not in ctx.source.columns]
            if unknown:
                raise SqlError(f"references column(s) not in {ctx.source.table}: {', '.join(unknown)}")
            local_expr[d["row"]] = expression_to_local(res["sql"])
        except SqlError as e:
            _fail(d, str(e))
            continue
        d["read_columns"] = cols
        if d["origin"] in ("llm", "cache") and d["source_field"] and d["source_field"] not in cols:
            result.findings.append(finding("warning", str(d["row"]),
                                           f'The expression for "{d["target_field"]}" does not use its source field '
                                           f'"{d["source_field"]}" — check it matches the rule'))

    # -- 5: run every expression on sampled rows (+ the STTM sample row) -------------------
    with warehouse.sandbox(ctx.source.table, sample_row(decisions), sample_limit, live_types) as box:
        for d in candidates:
            if d["status"] != "pending":
                continue
            local, cols = local_expr[d["row"]], d["read_columns"]
            to_type = duckdb_type(d["target_type"])
            try:
                out_type = box.describe(f"SELECT {local} AS v FROM {SANDBOX_VIEW}")[0][1]
                select = ", ".join([f"CAST(CAST(({local}) AS {to_type}) AS VARCHAR)"]
                                   + [f'CAST("{c}" AS VARCHAR)' for c in cols])
                _, rows = box.rows(f"SELECT {select} FROM {SANDBOX_VIEW}")  # every sampled row, all evaluated
            except LocalSqlError as e:
                _fail(d, str(e))
                continue
            examples, nulls = _examples(cols, rows)
            d.update(status="ok", error=None, output_type=out_type, examples=examples, nulls_introduced=nulls)
            if nulls:
                shown = ", ".join(repr(v) for v in nulls["examples"])
                result.findings.append(finding(
                    "info", str(d["row"]),
                    f'"{d["target_field"]}": {nulls["count"]} of {nulls["of"]} sampled values became NULL'
                    + (f" (e.g. {shown})" if shown else "") + " — expected if the rule discards bad data"))
            if (family(out_type), family(d["target_type"])) in LOSSY:
                result.findings.append(finding(
                    "warning", str(d["row"]),
                    f'"{d["target_field"]}" is computed as {out_type} and cast to {d["target_type"]} in the write '
                    "step — it worked on the sample, but other values may not convert"))

        # -- the files, as a whole ----------------------------------------------------------
        used = {c for d in decisions if d["status"] == "ok" for c in d.get("read_columns", [])}
        result.read_columns = [c for c in ctx.source.columns if c in used] or [next(iter(ctx.source.columns))]
        result.files = render_files(RenderInput(
            conventions=ctx.conventions, source=ctx.source, target=ctx.target, decisions=decisions,
            read_columns=result.read_columns, functions_name=fn, functions_require=ctx.functions_require,
            env_name=ctx.env_name, env_values=ctx.env_values))
        for f in result.files:
            if f["kind"] in ("source_params", "target_params"):
                project.define(f["path"], f["content"])  # params are includes of the generated SQLX
        try:
            local = statement_to_local(compile_pipeline(project, result.files, ctx, SANDBOX_ROWS_VIEW))
            described = box.describe(local)
            cols, rows = box.rows(f"SELECT CAST(COLUMNS(*) AS VARCHAR) FROM ({local})", limit=PREVIEW_ROWS)
            result.preview = {"columns": [c for c, _ in described], "types": [t for _, t in described],
                              "rows": [list(r) for r in rows]}
            if [c for c, _ in described] != list(ctx.target.columns):
                result.pipeline_error = "compiled pipeline columns do not match the target schema"
            result.pipeline_sql = statement_to_local(
                compile_pipeline(project, result.files, ctx, ctx.source.table))
        except (CompileError, SqlError, LocalSqlError) as e:
            result.pipeline_error = str(e)

    # -- cost model: bytes a BigQuery on-demand query would bill, pruned vs SELECT * -------
    contract = {c: col.type for c, col in ctx.source.columns.items() if c in live_types}
    per_col = warehouse.scan_bytes(ctx.source.table, contract)
    result.scan = {"readBytes": sum(per_col.get(c, 0) for c in result.read_columns),
                   "fullBytes": sum(per_col.values()),
                   "readColumns": len(result.read_columns), "totalColumns": len(contract)}
    return result

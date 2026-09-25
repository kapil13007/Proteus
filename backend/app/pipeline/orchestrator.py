"""Orchestrator: runs the stages in order, in a worker thread, and records everything.

  generation:  parse -> validate -> plan -> translate (LLM, cached) -> verify
                                              ^------ repair -------|   (only failing rows, bounded)
               ends at status awaiting_review — the human gate
  revision:    reviewer overrides / feedback -> translate changed rows -> verify -> awaiting_review
  execution:   replace_table -> audit -> publish          (after approval)

Control flow is plain Python on purpose: the loop is deterministic and bounded,
so a graph framework would add indirection without adding capability. Runs
execute on a small fixed pool, which also caps concurrent LLM usage.
"""
import logging
import time
import traceback
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from copy import deepcopy

from app import github
from app.config import settings
from app.dataform import CompileError
from app.dataform.compiler import DataformProject
from app.dataform.render import udf_template
from app.inputs import InputError
from app.inputs.types import compatible, family
from app.llm import client as llm_client
from app.llm.client import LlmError, list_price_usd
from app.llm.translator import Translator
from app.mapping import finding
from app.mapping.planner import plan
from app.mapping.validator import validate
from app.pipeline import S_AUDIT, S_EXECUTE, S_GENERATE, S_PARSE, S_PUBLISH, S_REVIEW, S_VALIDATE, S_VERIFY
from app.pipeline.context import RunContext, build_context
from app.pipeline.recorder import RunRecorder
from app.pipeline.verify import verify
from app.warehouse import get_warehouse

log = logging.getLogger("mapflow.pipeline")
_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="mapflow-run")


def submit(fn, *args):
    """Run a phase in the background; the API returns immediately and the UI polls."""
    return _pool.submit(fn, *args)


# --------------------------------------------------------------------------- #
#  Phase 1 — generation
# --------------------------------------------------------------------------- #

def run_generation(run_id: str) -> None:
    rec = RunRecorder(run_id)
    try:
        ctx = _parse_and_validate(rec)
        if ctx is None:
            return
        with ExitStack() as stack:
            project = _open_project(rec, ctx, stack)
            decisions = _plan(rec, ctx, project)
            _generate_and_verify(rec, ctx, project, decisions)
    except (InputError, CompileError) as e:
        _fail_run(rec, str(e))
    except Exception as e:  # noqa: BLE001 — surface anything to the run record
        log.error("run %s crashed:\n%s", run_id, traceback.format_exc())
        _fail_run(rec, f"unexpected error: {e}")


def _parse_and_validate(rec: RunRecorder) -> RunContext | None:
    run = rec.load()
    with rec.stage(S_PARSE, "parse"):
        rec.event("thought", "Reading the context: schemas, STTM sheet, folder structure, UDFs")
        ctx = build_context(run.id, run.inputs)
        rec.event("tool_result", f"STTM: {len(ctx.rows)} mapping rows · source {ctx.source.table} "
                                 f"({len(ctx.source.columns)} cols) → target {ctx.target.table} "
                                 f"({len(ctx.target.columns)} cols)")
        for line in ctx.conventions.evidence:
            rec.event("tool_result", f"folder structure: {line}")
        _prepare_source(rec, ctx)
        rec.update(source_table=ctx.source.table, target_table=ctx.target.table,
                   conventions=ctx.conventions.to_dict())

    with rec.stage(S_VALIDATE, "validate"):
        rec.event("tool_call", "validate_sttm(rows, source_schema, target_schema) — deterministic, 0 tokens")
        res = validate(ctx.rows, ctx.source, ctx.target)
        rec.add_findings([{**f, "stage": "validate"} for f in res["findings"] + res["errors"]])
        rec.update(mappings_validated=len(res["active_rows"]), mappings_excluded=res["excluded_count"])
        if res["errors"]:
            for e in res["errors"]:
                rec.event("tool_error", f"row {e['rows']}: {e['message']}")
            rec.event("thought", f"{len(res['errors'])} blocking error(s) in the sheet — stopping before any "
                                 "LLM call. Fix the sheet and start a new run.")
            _fail_run(rec, None)
            return None
        ctx.active_rows = res["active_rows"]
        warnings = sum(1 for f in res["findings"] if f["severity"] == "warning")
        rec.event("tool_result", f"{len(ctx.active_rows)} rows validated · {warnings} warning(s) · "
                                 f"{res['excluded_count']} excluded")
    return ctx


def _prepare_source(rec: RunRecorder, ctx: RunContext) -> None:
    """The source must exist in the local warehouse. If it doesn't, bootstrap it from its contract."""
    wh = get_warehouse()
    live = wh.table_columns(ctx.source.table)
    if live is None:
        sample: dict = {}
        for r in ctx.rows:
            if r["source_field"] and r["sample_data"]:
                sample.setdefault(r["source_field"], r["sample_data"])
        wh.create_from_contract(ctx.source, [sample] if sample else [])
        rec.event("thought", f"{ctx.source.table} is not in the local warehouse — created it from "
                             f"source_schema.md with {1 if sample else 0} sample row taken from the STTM")
        rec.add_findings([{**finding("info", "-", f"{ctx.source.table} did not exist locally, so it was created "
                                                  "from the source schema with the STTM's sample values only"),
                           "stage": "validate"}])
        return
    missing = [c for c in ctx.source.columns if c not in live]
    if missing:
        raise InputError(f"source_schema.md lists column(s) that the live table {ctx.source.table} "
                         f"does not have: {', '.join(missing)}")
    drift = [f"{c} is {live[c]} (schema says {col.type})" for c, col in ctx.source.columns.items()
             if not compatible(family(live[c]), col.family)]
    if drift:
        rec.add_findings([{**finding("warning", "-", "Live source types differ from source_schema.md: "
                                     + "; ".join(drift)), "stage": "validate"}])
    rec.event("tool_result", f"live table {ctx.source.table} matches the schema · {wh.row_count(ctx.source.table):,} rows")


def _open_project(rec: RunRecorder, ctx: RunContext, stack: ExitStack, quiet: bool = False) -> DataformProject:
    """Start V8 with the team's includes; closed automatically when the phase ends."""
    with rec.stage(S_GENERATE, "includes"):
        project = stack.enter_context(DataformProject(ctx.includes(), ctx.globals()))
        _load_includes(rec, ctx, project, quiet)
    return project


def _load_includes(rec: RunRecorder, ctx: RunContext, project: DataformProject, quiet: bool = False) -> None:
    if ctx.functions_js:
        ctx.catalog = project.udf_catalog(ctx.functions_path)
        cols = [u["name"] for u in ctx.catalog if u["kind"] == "column"]
        tables = [u["name"] for u in ctx.catalog if u["kind"] == "table"]
        if not quiet:
            rec.event("tool_result", f"{ctx.functions_path}: {len(cols)} column UDF(s) ({', '.join(cols) or 'none'})"
                      + (f" · {len(tables)} table-level helper(s) left for humans ({', '.join(tables)})" if tables else ""))
    if ctx.env_js:
        ctx.env_values = project.module_values(ctx.env_path)
        if not quiet:
            rec.event("tool_result", f"{ctx.env_path}: {', '.join(ctx.env_values) or 'no scalar values'}")
    if not quiet:
        rec.update(udf_catalog=ctx.catalog)


def _plan(rec: RunRecorder, ctx: RunContext, project: DataformProject) -> list[dict]:
    with rec.stage(S_GENERATE, "plan"):
        def expand(calls):
            results = project.expand([udf_template(ctx.functions_name, name, args) for name, args in calls])
            return [r["sql"] if r["ok"] else None for r in results]

        decisions = plan(ctx.active_rows, ctx.source, ctx.target, ctx.catalog, expand)
        counts = Counter(d["method"] for d in decisions)
        rec.event("thought", f"Routing {len(decisions)} rows: {counts['direct']} direct, {counts['cast']} cast, "
                             f"{counts['sql_logic']} sql_logic, {counts['udf']} UDF → "
                             f"{counts['llm']} need the LLM")
        for d in decisions:
            if d["method"] == "udf":
                rec.event("tool_result", f"row {d['row']} ({d['target_field']}): {d['rationale']}")
    return decisions


def _translator(rec: RunRecorder, ctx: RunContext) -> Translator:
    def on_usage(usage: dict, rows: int) -> None:
        rec.add_metrics({"llm": {**usage, "costUsd": list_price_usd(usage), "rowsSent": rows}})

    return Translator(llm_client.get_client(), source=ctx.source, catalog=ctx.catalog,
                      env_values=ctx.env_values, functions_name=ctx.functions_name, env_name=ctx.env_name,
                      on_usage=on_usage, on_event=rec.event)


def _generate_and_verify(rec: RunRecorder, ctx: RunContext, project: DataformProject,
                         decisions: list[dict]) -> None:
    translator = _translator(rec, ctx)
    todo = [d for d in decisions if d["status"] == "needs_llm"]
    if todo:
        with rec.stage(S_GENERATE, "llm"):
            translator.translate(todo)

    wh = get_warehouse()
    max_attempts = max(1, settings.max_repair_attempts)
    result = None
    for attempt in range(1, max_attempts + 1):
        rec.update(attempt_current=attempt, attempt_max=max_attempts)
        with rec.stage(S_VERIFY, "verify"):
            rec.event("tool_call", f"verify(pass {attempt}) — expand UDFs in V8, dry-run every column on "
                                   f"sampled rows in DuckDB")
            result = verify(ctx, project, wh, decisions, settings.sample_rows)
        failed = [d for d in decisions if d["status"] == "failed"]
        for d in failed:
            rec.event("tool_error", f"row {d['row']} ({d['target_field']}): {d['error']}")
        rec.event("tool_result", f"{len(decisions) - len(failed)}/{len(decisions)} columns verified")
        repairable = [d for d in failed if d["method"] in ("llm", "sql_logic", "cast")]
        if not failed or not repairable or attempt == max_attempts or translator.client is None:
            break
        rec.event("thought", f"Sending only the {len(repairable)} failing row(s) back to the LLM, "
                             "each with its exact error")
        with rec.stage(S_GENERATE, "llm"):
            translator.repair(repairable)

    stored = translator.store_verified(decisions)
    if stored:
        rec.event("tool_result", f"cached {stored} verified LLM answer(s) — an unchanged rerun costs 0 tokens")
    _finish_review(rec, ctx, decisions, result)


def _finish_review(rec: RunRecorder, ctx: RunContext, decisions: list[dict], result) -> None:
    failed = [d for d in decisions if d["status"] == "failed"]
    new = list(result.findings)
    for d in failed:
        new.append(finding("error", str(d["row"]), f'"{d["target_field"]}" could not be generated automatically '
                                                   f'({d["error"]}). Add an override or revise with feedback.'))
    for d in decisions:
        if d.get("repaired"):
            new.append(finding("warning", str(d["row"]), "The STTM's sql_logic failed verification and was rewritten "
                                                         "by the LLM — compare it with the sheet"))
    run = rec.load()
    kept = [f for f in (run.findings or []) if f.get("stage") != "verify"]
    origins = Counter(d["origin"] for d in decisions)
    rec.set_metrics(
        scan=result.scan,
        rows={"total": len(decisions), "deterministic": origins["rule"], "llm": origins["llm"],
              "cached": origins["cache"], "reviewer": origins["reviewer"], "failed": len(failed),
              "usingUdfs": sum(1 for d in decisions if d.get("udfs_used"))})
    common = dict(decisions=decisions, files=result.files, preview=result.preview,
                  pipeline_sql=result.pipeline_sql, findings=kept + [{**f, "stage": "verify"} for f in new],
                  attempt_current=None, attempt_max=None)

    if result.pipeline_error and not failed:
        rec.update(**common)
        _fail_run(rec, f"the generated files did not compile as a whole: {result.pipeline_error}")
        return
    rec.update(status="awaiting_review", current_step=S_REVIEW, step_failed=False, **common)
    if failed:
        rec.event("thought", f"{len(failed)} column(s) need a human — pausing for review with them flagged")
    else:
        rec.event("thought", "Every column verified on sample data — pausing for human review")


# --------------------------------------------------------------------------- #
#  Phase 1b — revision (reviewer overrides and/or feedback)
# --------------------------------------------------------------------------- #

def run_revision(run_id: str, overrides: list[dict], feedback: str, user: str) -> None:
    rec = RunRecorder(run_id)
    try:
        run = rec.load()
        ctx = build_context(run.id, run.inputs)
        decisions = deepcopy(run.decisions or [])
        by_row = {d["row"]: d for d in decisions}
        with ExitStack() as stack:
            project = _open_project(rec, ctx, stack, quiet=True)
            changed = []
            for o in overrides:
                d = by_row.get(int(o.get("row", -1)))
                expr = str(o.get("expression") or "").strip()
                if d is None or not expr:
                    continue
                d.update(method="reviewer", origin="reviewer", udf=None, sql=expr, status="pending",
                         error=None, repaired=False, rationale=f"Override by {user}")
                changed.append(d["row"])
                rec.event("tool_result", f"row {d['row']} ({d['target_field']}): override by {user}")
            if feedback:
                try:
                    with rec.stage(S_GENERATE, "llm"):
                        changed += [d["row"] for d in _translator(rec, ctx).revise(decisions, feedback)]
                except LlmError as e:
                    rec.event("tool_error", f"could not apply feedback: {e}")
            rec.update(revisions=list(run.revisions or []) + [{
                "by": user, "at": int(time.time() * 1000), "feedback": feedback,
                "overrides": [int(o["row"]) for o in overrides if o.get("row") is not None],
                "changedRows": sorted(set(changed))}])
            _generate_and_verify(rec, ctx, project, decisions)
    except (InputError, CompileError) as e:
        _fail_run(rec, str(e))
    except Exception as e:  # noqa: BLE001
        log.error("revision of %s crashed:\n%s", run_id, traceback.format_exc())
        _fail_run(rec, f"unexpected error: {e}")


# --------------------------------------------------------------------------- #
#  Phase 2 — execution (after approval)
# --------------------------------------------------------------------------- #

def run_execution(run_id: str, user: str) -> None:
    rec = RunRecorder(run_id)
    try:
        run = rec.load()
        ctx = build_context(run.id, run.inputs)
        wh = get_warehouse()
        with rec.stage(S_EXECUTE, "execute"):
            rec.event("tool_call", f"replace_table({ctx.target.table}) — CREATE OR REPLACE TABLE … AS SELECT")
            written = wh.replace_table(run.pipeline_sql, ctx.target.table)
            rec.event("tool_result", f"{written:,} rows written to {ctx.target.table}")
        with rec.stage(S_AUDIT, "audit"):
            audit = wh.audit(ctx.source.table, ctx.target)
            for c in audit["checks"]:
                rec.event("tool_result" if c["ok"] else "tool_error", f"audit · {c['name']}: {c['detail']}")
            rec.update(audit=audit)
        if audit["failedCheck"]:
            rec.event("thought", "Audit failed — not publishing code that fails its own assertions")
            _fail_run(rec, None)
            return
        with rec.stage(S_PUBLISH, "publish"):
            rec.event("tool_call", f"publish({len(run.files)} files) → "
                                   f"{settings.github_repo or 'GitHub (not configured)'}")
            res = github.publish(run.files, f"mapflow: {ctx.target.table} from {ctx.source.table} "
                                            f"({run.id}, approved by {user})")
            rec.update(publish=res)
        if res["pushed"]:
            rec.event("tool_result", f"commit {res['sha']} · {res['url']}")
        elif res["skipped"]:
            rec.event("tool_result", f"publish skipped: {res['reason']}")
        else:
            rec.event("tool_error", f"publish failed: {res['reason']}")
            _fail_run(rec, None)
            return
        rec.event("thought", "Run complete — data written, audit passed")
        rec.update(status="succeeded", step_failed=False, duration_sec=_elapsed(run.started_at))
    except Exception as e:  # noqa: BLE001
        log.error("execution of %s crashed:\n%s", run_id, traceback.format_exc())
        _fail_run(rec, f"execution failed: {e}")


# --------------------------------------------------------------------------- #

def _elapsed(started_at_ms: int) -> float:
    return round(time.time() - (started_at_ms or 0) / 1000, 1)


def _fail_run(rec: RunRecorder, message: str | None) -> None:
    if message:
        rec.event("tool_error", message)
    run = rec.load()
    rec.update(status="failed", step_failed=True, error=message or (run.error if run else None),
               attempt_current=None, attempt_max=None,
               duration_sec=_elapsed(run.started_at) if run else None)

"""The Mapfl0w agent.

Two LangGraph StateGraphs sharing one state shape:

  generation_graph:  parse -> validate -> generate -> dry_run
                                             ^            |
                                             +-- retry ---+   (conditional edge, max N attempts)
                     ends with status = awaiting_review  (the human gate)

  execution_graph:   execute -> push_github -> audit      (runs after /approve)

The pause-for-review is implemented as the boundary between the two graphs and
persisted in Postgres — a deliberate MVP simplification of LangGraph's
interrupt()+checkpointer that survives server restarts for free.
"""
import json
import re
import time
from typing import TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph

from app.agent import prompts
from app.config import settings
from app.services.runstore import add_findings, push_feed, update_run
from app.tools import github_tools, postgres_tools
from app.tools.parsers import ParseError, parse_schema_md, parse_sttm
from app.tools.sqlx import build_insert, extract_sqlx_from_llm
from app.tools.validator import validate

# Step indices must match the frontend's STEP_LABELS
S_PARSE, S_VALIDATE, S_GENERATE, S_DRYRUN, S_REVIEW, S_PUSH, S_EXECUTE, S_AUDIT = range(8)


class AgentState(TypedDict, total=False):
    run_id: str
    # raw inputs
    source_schema_md: str
    target_schema_md: str
    sttm_filename: str
    sttm_bytes: bytes
    repo_structure_md: str
    udf_definitions_md: str
    # parsed
    source_schema: dict
    target_schema: dict
    sttm_rows: list
    active_rows: list
    # working
    sqlx_code: str
    sqlx_path: str
    insert_sql: str
    dry_run_error: str
    attempt: int
    validator_notes: str
    failed: bool
    llm_prompt_tokens: int
    llm_completion_tokens: int


def _llm():
    from langchain_groq import ChatGroq
    return ChatGroq(model=settings.groq_model, api_key=settings.groq_api_key, temperature=0)


def _fmt_schema(s: dict) -> str:
    lines = [f'- {n}: {c["type"]}' + ("" if c["nullable"] else " NOT NULL")
             for n, c in s["columns"].items()]
    return f'Table {s["table"]}\n' + "\n".join(lines)


def _sqlx_path(target_table: str, repo_md: str) -> str:
    name = target_table.split(".")[-1]
    m = re.search(r"(definitions/[\w/-]+/)", repo_md)
    folder = m.group(1) if m else "definitions/marts/"
    return f"{folder}{name}.sqlx"


# --------------------------------------------------------------------------- #
#  Generation graph nodes
# --------------------------------------------------------------------------- #

def node_parse(state: AgentState) -> AgentState:
    rid = state["run_id"]
    update_run(rid, current_step=S_PARSE)
    push_feed(rid, "thought", "Reading input files")

    push_feed(rid, "tool_call", f'parse_sttm({state["sttm_filename"]})')
    rows, csv_text = parse_sttm(state["sttm_filename"], state["sttm_bytes"])
    push_feed(rid, "tool_result", f"{len(rows)} mapping rows parsed")
    update_run(rid, sttm_csv=csv_text)

    push_feed(rid, "tool_call", "parse_schema(source_schema.md)")
    source = parse_schema_md(state["source_schema_md"])
    push_feed(rid, "tool_result", f'{source["table"]} · {len(source["columns"])} columns')

    push_feed(rid, "tool_call", "parse_schema(target_schema.md)")
    target = parse_schema_md(state["target_schema_md"])
    push_feed(rid, "tool_result", f'{target["table"]} · {len(target["columns"])} columns')

    # Cross-check the MD against the live database — the MD is the contract,
    # Postgres is the truth. Drift gets surfaced immediately.
    push_feed(rid, "tool_call", f'get_table_schema({source["table"]})')
    live = postgres_tools.get_table_schema(source["table"])
    missing = [c for c in source["columns"] if c not in live["columns"]]
    if missing:
        raise ParseError(
            f"Schema MD lists columns not present in live table {source['table']}: {', '.join(missing)}")
    push_feed(rid, "tool_result", f'live table verified · {len(live["columns"])} columns')

    update_run(rid, target_table=target["table"])
    return {"source_schema": source, "target_schema": target, "sttm_rows": rows}


def node_validate(state: AgentState) -> AgentState:
    rid = state["run_id"]
    update_run(rid, current_step=S_VALIDATE)
    push_feed(rid, "tool_call", "validate_mapping(rows, source_schema, target_schema)")

    result = validate(state["sttm_rows"], state["source_schema"], state["target_schema"])
    add_findings(rid, result["findings"])
    update_run(rid,
               mappings_validated=len(result["active_rows"]),
               mappings_excluded=result["excluded_count"])

    if result["errors"]:
        add_findings(rid, result["errors"])
        for e in result["errors"]:
            push_feed(rid, "tool_error", f'row {e["rows"]}: {e["message"]}')
        push_feed(rid, "thought",
                  f'{len(result["errors"])} blocking error(s) — refusing to generate against a broken mapping')
        return {"failed": True}

    warn = sum(1 for f in result["findings"] if f["severity"] == "warning")
    push_feed(rid, "tool_result",
              f'{len(result["active_rows"])} rows validated · {warn} warning(s) · {result["excluded_count"]} excluded')
    notes = "\n".join(f'- row {f["rows"]}: {f["message"]}' for f in result["findings"]) or "none"
    return {"active_rows": result["active_rows"], "validator_notes": notes}


def node_generate(state: AgentState) -> AgentState:
    rid = state["run_id"]
    update_run(rid, current_step=S_GENERATE)
    attempt = state.get("attempt", 0) + 1
    target = state["target_schema"]
    order = [r["target_field"] for r in state["active_rows"]]
    path = _sqlx_path(target["table"], state["repo_structure_md"])

    llm = _llm()
    if state.get("dry_run_error"):
        push_feed(rid, "thought",
                  "Reading the dry-run error and correcting the generated code")
        push_feed(rid, "tool_call", f"generate_sqlx() — correction attempt {attempt}")
        msg = prompts.CORRECT.format(
            error=state["dry_run_error"],
            previous=state["sqlx_code"],
            target_field_order=", ".join(order),
        )
    else:
        push_feed(rid, "tool_call", "generate_sqlx()")
        msg = prompts.GENERATE.format(
            source_schema=_fmt_schema(state["source_schema"]),
            target_schema=_fmt_schema(target),
            target_table=target["table"],
            sttm_rows=json.dumps([{k: v for k, v in r.items() if k != "_row"}
                                  for r in state["active_rows"]], indent=1),
            repo_structure=state["repo_structure_md"],
            udf_definitions=state["udf_definitions_md"] or "none provided",
            validator_notes=state["validator_notes"],
            target_field_order=", ".join(order),
            sqlx_path=path,
        )

    reply = llm.invoke([SystemMessage(content=prompts.SYSTEM), HumanMessage(content=msg)])
    sqlx = extract_sqlx_from_llm(reply.content)
    lines = sqlx.count("\n") + 1
    push_feed(rid, "tool_result", f"{lines} lines of .sqlx written")

    usage = getattr(reply, "usage_metadata", None) or {}
    prompt_tok = state.get("llm_prompt_tokens", 0) + usage.get("input_tokens", 0)
    completion_tok = state.get("llm_completion_tokens", 0) + usage.get("output_tokens", 0)
    llm_cost = (prompt_tok * settings.groq_price_per_1m_input
                + completion_tok * settings.groq_price_per_1m_output) / 1_000_000

    update_run(rid, sqlx_code=sqlx, sqlx_path=path, llm_attempts=attempt,
               llm_prompt_tokens=prompt_tok, llm_completion_tokens=completion_tok,
               llm_cost_usd=round(llm_cost, 4))
    return {"sqlx_code": sqlx, "sqlx_path": path, "attempt": attempt, "dry_run_error": "",
            "llm_prompt_tokens": prompt_tok, "llm_completion_tokens": completion_tok}


def node_dry_run(state: AgentState) -> AgentState:
    rid = state["run_id"]
    update_run(rid, current_step=S_DRYRUN,
               attempt_current=state["attempt"], attempt_max=settings.max_dry_run_attempts)
    push_feed(rid, "tool_call", f'pg_dry_run({state["sqlx_path"].split("/")[-1]})')

    try:
        insert_sql = build_insert(state["sqlx_code"], state["target_schema"]["table"],
                                  [r["target_field"] for r in state["active_rows"]])
        result = postgres_tools.dry_run(insert_sql)
    except Exception as e:
        result = {"success": False, "error": str(e)}

    if not result["success"]:
        push_feed(rid, "tool_error", f'error: {result["error"]}')
        return {"dry_run_error": result["error"]}

    est_gb = round(result["est_bytes"] / 1e9, 4)
    push_feed(rid, "tool_result",
              f'dry run passed · ~{result["est_rows"]} rows · est. {est_gb} GB')
    update_run(rid, cost_gb=est_gb, cost_usd=0.0, attempt_current=None, attempt_max=None)
    return {"insert_sql": insert_sql, "dry_run_error": ""}


def route_after_dry_run(state: AgentState) -> str:
    if not state.get("dry_run_error"):
        return "review"
    if state["attempt"] >= settings.max_dry_run_attempts:
        push_feed(state["run_id"], "thought",
                  f"Dry-run still failing after {state['attempt']} attempts — escalating to human")
        return "escalate"
    return "retry"


def node_review(state: AgentState) -> AgentState:
    rid = state["run_id"]
    update_run(rid, current_step=S_REVIEW, status="awaiting_review")
    push_feed(rid, "thought", "All checks green. Pausing for human review")
    return {}


def node_escalate(state: AgentState) -> AgentState:
    rid = state["run_id"]
    update_run(rid, status="failed", step_failed=True)
    add_findings(rid, [{"id": "f_escalate", "severity": "warning", "rows": "-",
                        "message": f"Dry-run failed {state['attempt']} times. Last error: {state['dry_run_error']}"}])
    return {"failed": True}


def build_generation_graph():
    g = StateGraph(AgentState)
    g.add_node("parse", node_parse)
    g.add_node("validate", node_validate)
    g.add_node("generate", node_generate)
    g.add_node("dry_run", node_dry_run)
    g.add_node("review", node_review)
    g.add_node("escalate", node_escalate)

    g.set_entry_point("parse")
    g.add_edge("parse", "validate")
    g.add_conditional_edges("validate",
                            lambda s: "stop" if s.get("failed") else "go",
                            {"stop": END, "go": "generate"})
    g.add_edge("generate", "dry_run")
    g.add_conditional_edges("dry_run", route_after_dry_run,
                            {"review": "review", "retry": "generate", "escalate": "escalate"})
    g.add_edge("review", END)
    g.add_edge("escalate", END)
    return g.compile()


# --------------------------------------------------------------------------- #
#  Execution graph nodes (after approval)
# --------------------------------------------------------------------------- #

def node_push(state: AgentState) -> AgentState:
    rid = state["run_id"]
    update_run(rid, current_step=S_PUSH, status="running")
    push_feed(rid, "tool_call",
              f'github_push({settings.github_repo or "local"}, {state["sqlx_path"]})')
    res = github_tools.push_file(state["sqlx_path"], state["sqlx_code"],
                                 f'mapflow: add {state["sqlx_path"].split("/")[-1]}')
    if res["pushed"]:
        push_feed(rid, "tool_result", f'commit {res["sha"]} pushed · {res["url"]}')
        update_run(rid, workflow_id=res["sha"])
    else:
        push_feed(rid, "tool_result", f'push skipped: {res["reason"]}')
    return {}


def node_execute(state: AgentState) -> AgentState:
    rid = state["run_id"]
    update_run(rid, current_step=S_EXECUTE)
    target = state["target_schema"]["table"]
    push_feed(rid, "tool_call", f"execute_transformation({target}) — full refresh")
    rows = postgres_tools.execute_insert(state["insert_sql"], target)
    push_feed(rid, "tool_result", f"{rows:,} rows written to {target}")
    return {}


def node_audit(state: AgentState) -> AgentState:
    rid = state["run_id"]
    update_run(rid, current_step=S_AUDIT)
    target = state["target_schema"]
    required = [n for n, c in target["columns"].items() if not c["nullable"]]
    push_feed(rid, "tool_call", f'audit({state["source_schema"]["table"]} vs {target["table"]})')
    a = postgres_tools.audit(state["source_schema"]["table"], target["table"], required)

    ok = a["counts_match"] and a["null_violations"] == 0
    push_feed(rid, "tool_result",
              f'{a["rows_written"]:,} rows written · counts {"match" if a["counts_match"] else "MISMATCH"}'
              f' · {a["null_violations"]} null violation(s)')
    push_feed(rid, "thought",
              "Run complete. Audit passed all checks" if ok else "Run complete with audit findings")
    update_run(rid,
               status="succeeded" if ok else "failed",
               step_failed=not ok,
               audit_rows_written=a["rows_written"],
               audit_counts_match=a["counts_match"],
               audit_nulls_check=a["null_violations"] == 0,
               audit_failed_check=None if ok else (
                   "row counts do not match" if not a["counts_match"]
                   else f'nulls found in required column "{a["bad_col"]}"'))
    return {}


def build_execution_graph():
    g = StateGraph(AgentState)
    g.add_node("push_github", node_push)
    g.add_node("execute", node_execute)
    g.add_node("audit", node_audit)
    g.set_entry_point("push_github")
    g.add_edge("push_github", "execute")
    g.add_edge("execute", "audit")
    return g.compile()


generation_graph = build_generation_graph()
execution_graph = build_execution_graph()


# --------------------------------------------------------------------------- #
#  Thread entrypoints used by the API layer
# --------------------------------------------------------------------------- #

def run_generation(state: AgentState) -> None:
    rid = state["run_id"]
    started = time.time()
    try:
        generation_graph.invoke(state)
    except ParseError as e:
        push_feed(rid, "tool_error", str(e))
        update_run(rid, status="failed", step_failed=True)
    except Exception as e:  # noqa: BLE001 — surface anything to the run record
        push_feed(rid, "tool_error", f"unexpected: {e}")
        update_run(rid, status="failed", step_failed=True)
    finally:
        snap_status = None
        from app.services.runstore import get_run_snapshot
        snap = get_run_snapshot(rid)
        snap_status = snap.status if snap else None
        if snap_status in ("failed",):
            update_run(rid, duration_sec=round(time.time() - started, 1))


def run_execution(state: AgentState, started_at_ms: int) -> None:
    rid = state["run_id"]
    try:
        execution_graph.invoke(state)
    except Exception as e:  # noqa: BLE001
        push_feed(rid, "tool_error", f"unexpected: {e}")
        update_run(rid, status="failed", step_failed=True)
    finally:
        update_run(rid, duration_sec=round((time.time() * 1000 - started_at_ms) / 1000, 1))

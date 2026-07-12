"""Deterministic STTM validator. Pure code — runs before any LLM call.

Produces findings: {"severity": "error"|"warning"|"info", "rows": "12", "message": "..."}
The frontend renders warning/info; any error stops the run at the validate step.
"""
import uuid

# Casts we consider safe without explicit sql_logic (source -> target family)
_TYPE_FAMILY = {
    "VARCHAR": "text", "TEXT": "text", "STRING": "text", "CHAR": "text",
    "INT": "int", "INTEGER": "int", "BIGINT": "int", "SMALLINT": "int",
    "FLOAT": "float", "FLOAT64": "float", "DOUBLE": "float", "NUMERIC": "float", "DECIMAL": "float",
    "DATE": "date", "TIMESTAMP": "timestamp", "DATETIME": "timestamp",
    "BOOL": "bool", "BOOLEAN": "bool",
}

_LOSSY = {("float", "int"), ("text", "int"), ("text", "float"), ("text", "date"),
          ("text", "timestamp"), ("timestamp", "date"), ("text", "bool")}


def _fam(t: str) -> str:
    return _TYPE_FAMILY.get(t.upper().split("(")[0].strip(), "other")


def _f(severity: str, rows: str, message: str) -> dict:
    return {"id": f"f_{uuid.uuid4().hex[:8]}", "severity": severity, "rows": rows, "message": message}


def validate(sttm_rows: list[dict], source: dict, target: dict) -> dict:
    """Returns {findings, errors, active_rows, excluded_count}."""
    findings: list[dict] = []
    errors: list[dict] = []

    src_cols = source["columns"]
    tgt_cols = target["columns"]

    # --- Status filtering: only Validated rows are executed -------------------
    active, excluded = [], []
    for r in sttm_rows:
        status = r.get("mapping_status", "").strip().lower()
        if status in ("", "validated", "valid", "approved"):
            active.append(r)
        else:
            excluded.append(r)
    if excluded:
        rows = ", ".join(str(r["_row"]) for r in excluded)
        findings.append(_f("info", rows, f'{len(excluded)} row(s) not marked "Validated" — excluded from generation'))

    if not active:
        errors.append(_f("error", "-", "No validated mapping rows remain after status filtering"))
        return {"findings": findings, "errors": errors, "active_rows": [], "excluded_count": len(excluded)}

    # --- Existence checks ------------------------------------------------------
    for r in active:
        if r["source_field"] and r["source_field"] not in src_cols:
            errors.append(_f("error", str(r["_row"]),
                             f'Source field "{r["source_field"]}" does not exist in {source["table"]}'))
        if r["target_field"] and r["target_field"] not in tgt_cols:
            errors.append(_f("error", str(r["_row"]),
                             f'Target field "{r["target_field"]}" does not exist in {target["table"]}'))

    # --- Duplicate target mappings ---------------------------------------------
    seen: dict[str, int] = {}
    for r in active:
        tf = r["target_field"]
        if tf in seen:
            errors.append(_f("error", f"{seen[tf]}, {r['_row']}",
                             f'Target field "{tf}" is mapped more than once'))
        seen[tf] = r["_row"]

    # --- Required target columns with no mapping at all -------------------------
    mapped_targets = {r["target_field"] for r in active}
    for name, col in tgt_cols.items():
        if not col["nullable"] and name not in mapped_targets:
            errors.append(_f("error", "-",
                             f'Target column "{name}" is NOT NULL but has no mapping row'))

    # --- Nullability conflicts ---------------------------------------------------
    for r in active:
        sf, tf = r["source_field"], r["target_field"]
        if sf not in src_cols or tf not in tgt_cols:
            continue
        src_nullable = src_cols[sf]["nullable"] or r.get("nullable", "").strip().upper() in ("YES", "TRUE", "Y")
        tgt_not_null = not tgt_cols[tf]["nullable"]
        has_default = bool(r.get("default_value", "").strip())
        has_logic = bool(r.get("sql_logic", "").strip())
        if src_nullable and tgt_not_null and not has_default and not has_logic:
            errors.append(_f("error", str(r["_row"]),
                             f'"{sf}" is nullable but "{tf}" is NOT NULL — no default value or handling logic given'))
        elif src_nullable and tgt_not_null and has_default:
            findings.append(_f("info", str(r["_row"]),
                               f'Nullable "{sf}" → NOT NULL "{tf}": will wrap in COALESCE with default {r["default_value"]!r}'))

    # --- Type compatibility -------------------------------------------------------
    for r in active:
        sf, tf = r["source_field"], r["target_field"]
        if sf not in src_cols or tf not in tgt_cols:
            continue
        pair = (_fam(src_cols[sf]["type"]), _fam(tgt_cols[tf]["type"]))
        if pair[0] != pair[1] and not r.get("sql_logic", "").strip():
            sev = "warning" if pair in _LOSSY else "info"
            findings.append(_f(sev, str(r["_row"]),
                               f'{sf} ({src_cols[sf]["type"]}) → {tf} ({tgt_cols[tf]["type"]}) with no sql_logic — cast will be generated'))

    # --- Lookup tables we can't resolve locally -----------------------------------
    for r in active:
        if r.get("lookup_table", "").strip():
            findings.append(_f("warning", str(r["_row"]),
                               f'Row references lookup table "{r["lookup_table"]}" — verify the generated join/CASE logic'))

    return {"findings": findings, "errors": errors, "active_rows": active, "excluded_count": len(excluded)}

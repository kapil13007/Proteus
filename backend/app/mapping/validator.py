"""STTM validator. Pure code, runs before any LLM call, costs nothing.

Anything a spreadsheet check can catch should never reach the LLM: a mapping to
a column that doesn't exist, two rows writing one target column, a NOT NULL
target with no way to fill it. Errors stop the run; warnings and info go to the
reviewer with the spreadsheet row numbers.
"""
import re

from app.inputs.schema import TableSchema
from app.inputs.types import family, is_lossy
from app.mapping import finding

ACTIVE_STATUSES = {"", "validated", "valid", "approved", "final", "done", "ready"}

DIRECT_RULE = re.compile(
    r"^\s*(copy|copy as[- ]is|as[- ]is|direct(ly)?(\s+(move|map|mapping|copy|load))?|"
    r"straight\s+(move|map|copy)|1\s*[:-]\s*1|one[- ]to[- ]one|pass[- ]?through|"
    r"no\s+(transformation|change)s?( required)?|same as source|(move|load) as[- ]is|none|n/?a|-)\s*\.?\s*$",
    re.IGNORECASE,
)


def is_direct_rule(rule: str) -> bool:
    return not rule.strip() or bool(DIRECT_RULE.match(rule))


def _same_table(sttm_value: str, schema: TableSchema) -> bool:
    v = sttm_value.strip().strip("`").lower()
    return not v or v in (schema.table.lower(), schema.name.lower()) or v.endswith("." + schema.table.lower())


def validate(rows: list[dict], source: TableSchema, target: TableSchema) -> dict:
    """Returns {findings, errors, active_rows, excluded_count}."""
    findings: list[dict] = []
    errors: list[dict] = []
    src, tgt = source.columns, target.columns

    active, excluded = [], []
    for r in rows:
        (active if r.get("mapping_status", "").strip().lower() in ACTIVE_STATUSES else excluded).append(r)
    if excluded:
        findings.append(finding("info", ", ".join(str(r["_row"]) for r in excluded),
                                f"{len(excluded)} row(s) not marked Validated — excluded from generation"))
    if not active:
        errors.append(finding("error", "-", "No validated mapping rows remain after status filtering"))
        return {"findings": findings, "errors": errors, "active_rows": [], "excluded_count": len(excluded)}

    for r in active:
        row = str(r["_row"])
        # One source table and one target table per run (joins are out of scope).
        if not _same_table(r["source_table"], source):
            errors.append(finding("error", row, f'Row reads from "{r["source_table"]}" but the source schema is '
                                                f"{source.table}. Multi-source mappings (joins) are not supported yet."))
        if not _same_table(r["target_table"], target):
            errors.append(finding("error", row, f'Row writes to "{r["target_table"]}" but the target schema is {target.table}.'))
        # Existence
        if r["source_field"] and r["source_field"] not in src:
            errors.append(finding("error", row, f'Source field "{r["source_field"]}" does not exist in {source.table}'))
        if r["target_field"] and r["target_field"] not in tgt:
            errors.append(finding("error", row, f'Target field "{r["target_field"]}" does not exist in {target.table}'))
        if not r["target_field"]:
            errors.append(finding("error", row, "Row has no target field"))
        if not r["source_field"] and not r["sql_logic"] and is_direct_rule(r["transformation_rule"]):
            errors.append(finding("error", row, "Row has no source field and no logic — nothing to map"))
        # The sheet's own type columns disagree with the schema docs: the schema wins.
        for side, col, declared, cols in (("source", r["source_field"], r["source_type"], src),
                                          ("target", r["target_field"], r["target_type"], tgt)):
            if declared and col in cols and family(declared) not in ("other", cols[col].family):
                findings.append(finding("warning", row, f'STTM says {side} "{col}" is {declared}, schema says '
                                                        f"{cols[col].type} — using the schema"))

    # Two rows writing the same target column
    seen: dict[str, int] = {}
    for r in active:
        tf = r["target_field"]
        if tf in seen:
            errors.append(finding("error", f"{seen[tf]}, {r['_row']}", f'Target field "{tf}" is mapped more than once'))
        seen.setdefault(tf, r["_row"])

    # Target columns with no mapping row
    mapped = {r["target_field"] for r in active}
    for name, col in tgt.items():
        if name in mapped:
            continue
        if not col.nullable:
            errors.append(finding("error", "-", f'Target column "{name}" is NOT NULL but has no mapping row'))
        else:
            findings.append(finding("info", "-", f'Target column "{name}" has no mapping row — it will be written as NULL'))

    # Nullability and type conversions
    for r in active:
        sf, tf, row = r["source_field"], r["target_field"], str(r["_row"])
        if sf not in src or tf not in tgt:
            continue
        has_default = bool(r["default_value"].strip())
        has_logic = bool(r["sql_logic"].strip())
        direct = not has_logic and is_direct_rule(r["transformation_rule"])
        src_nullable = src[sf].nullable or r.get("nullable", "").strip().upper() in ("YES", "Y", "TRUE")
        if src_nullable and not tgt[tf].nullable and not has_default:
            if direct:
                errors.append(finding("error", row, f'"{sf}" is nullable but "{tf}" is NOT NULL, and the row is a '
                                                    "straight copy with no default value"))
            elif not has_logic:
                findings.append(finding("warning", row, f'"{sf}" is nullable but "{tf}" is NOT NULL and no default '
                                                        "is given — the nonNull audit will catch any gap"))
        if direct and is_lossy(src[sf].type, tgt[tf].type):
            findings.append(finding("warning", row, f"{sf} ({src[sf].type}) → {tf} ({tgt[tf].type}) is a lossy "
                                                    "conversion: SAFE_CAST is used, so unconvertible values become NULL"))
        if r["lookup_table"].strip() and not has_logic:
            findings.append(finding("info", row, f'References lookup "{r["lookup_table"]}" — the agent will look '
                                                 "for a matching UDF; verify the result"))

    return {"findings": findings, "errors": errors, "active_rows": active, "excluded_count": len(excluded)}

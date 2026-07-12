"""Parsers for the five uploaded files.

Schema MD format (strict, documented in sample_inputs/):

    # Table: raw.clinical_patients
    | column | type | nullable | description |
    |---|---|---|---|
    | patient_id | VARCHAR | NO | Unique patient id |

STTM sheet: CSV or Excel with the canonical headers below (case/space tolerant).
"""
import io
import re

import pandas as pd

STTM_CANONICAL = [
    "source_table", "source_field", "source_type", "nullable", "sample_data",
    "transformation_rule", "sql_logic", "lookup_table", "default_value",
    "target_table", "target_field", "target_type", "mapping_status",
]


class ParseError(Exception):
    pass


def parse_schema_md(md: str) -> dict:
    """Returns {"table": "raw.clinical_patients", "columns": {name: {type, nullable}}}"""
    m = re.search(r"^#\s*Table:\s*([\w.]+)", md, flags=re.MULTILINE)
    if not m:
        raise ParseError("Schema MD must start with a line like '# Table: raw.clinical_patients'")
    table = m.group(1).strip()

    columns: dict[str, dict] = {}
    for line in md.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 3:
            continue
        name = cells[0]
        if name.lower() in ("column", "") or set(name) <= {"-", ":", " "}:
            continue  # header or separator row
        columns[name] = {
            "type": cells[1].upper(),
            "nullable": cells[2].strip().upper() in ("YES", "TRUE", "Y", "NULLABLE"),
            "description": cells[3] if len(cells) > 3 else "",
        }
    if not columns:
        raise ParseError(f"No column rows found in schema MD for table {table}")
    return {"table": table, "columns": columns}


def _normalize_header(h: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(h).strip().lower()).strip("_")


def parse_sttm(filename: str, raw: bytes) -> tuple[list[dict], str]:
    """Accepts CSV or Excel bytes. Returns (rows, csv_text_for_storage)."""
    lower = filename.lower()
    try:
        if lower.endswith((".xlsx", ".xls")):
            df = pd.read_excel(io.BytesIO(raw), dtype=str)
        else:
            df = pd.read_csv(io.BytesIO(raw), dtype=str)
    except Exception as e:
        raise ParseError(f"Could not read STTM sheet: {e}") from e

    df.columns = [_normalize_header(c) for c in df.columns]
    missing = [c for c in ("source_field", "target_field", "target_table") if c not in df.columns]
    if missing:
        raise ParseError(f"STTM sheet is missing required columns: {', '.join(missing)}")

    for col in STTM_CANONICAL:
        if col not in df.columns:
            df[col] = ""
    df = df[STTM_CANONICAL].fillna("")

    rows = []
    for i, rec in enumerate(df.to_dict(orient="records")):
        rec = {k: str(v).strip() for k, v in rec.items()}
        rec["_row"] = i + 2  # 1-based + header row, matches what users see in a spreadsheet
        if rec["source_field"] or rec["target_field"]:
            rows.append(rec)
    if not rows:
        raise ParseError("STTM sheet has no mapping rows")
    return rows, df.to_csv(index=False)

"""STTM sheet parser (CSV or Excel).

Real mapping sheets never agree on headers ("Source Column", "src_field",
"Business Logic"...), so headers are normalised and matched against aliases.
Exact canonical names always win over aliases. Every row keeps its spreadsheet
row number (`_row`) so findings and generated SQL point back to the line the
analyst actually sees.
"""
import io
import re

import pandas as pd

from app.inputs import InputError

CANONICAL = [
    "source_table", "source_field", "source_type", "nullable", "sample_data",
    "transformation_rule", "sql_logic", "lookup_table", "default_value",
    "target_table", "target_field", "target_type", "mapping_status",
]

_ALIASES = {
    "source_field": ["source_column", "src_field", "src_column", "source_col",
                     "source_attribute", "source_field_name", "source_column_name"],
    "target_field": ["target_column", "tgt_field", "tgt_column", "target_col",
                     "target_attribute", "target_field_name", "target_column_name"],
    "source_table": ["src_table", "source_table_name", "source_entity"],
    "target_table": ["tgt_table", "target_table_name", "target_entity"],
    "source_type": ["source_data_type", "src_type", "source_datatype"],
    "target_type": ["target_data_type", "tgt_type", "target_datatype"],
    "transformation_rule": ["transformation", "business_rule", "business_logic",
                            "transformation_logic", "mapping_rule", "rule", "logic"],
    "sql_logic": ["sql", "sql_expression", "sql_transformation", "expression", "derivation"],
    "default_value": ["default", "default_val"],
    "mapping_status": ["status", "mapping_state"],
    "sample_data": ["sample", "sample_value", "example", "example_value"],
    "lookup_table": ["lookup", "reference_table"],
    "nullable": ["source_nullable", "is_nullable"],
}

_REQUIRED = ("source_field", "target_field")


def _normalize_header(h: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(h).strip().lower()).strip("_")


def _map_headers(headers: list[str]) -> dict[str, str]:
    """normalised sheet header -> canonical name (canonical names win, then aliases in order)."""
    normed = {_normalize_header(h): h for h in headers}
    mapping: dict[str, str] = {}
    for canon in CANONICAL:
        if canon in normed:
            mapping[canon] = normed[canon]
    for canon, aliases in _ALIASES.items():
        if canon in mapping:
            continue
        for alias in aliases:
            if alias in normed and normed[alias] not in mapping.values():
                mapping[canon] = normed[alias]
                break
    return mapping


def _read_frames(filename: str, raw: bytes) -> list[pd.DataFrame]:
    lower = filename.lower()
    try:
        if lower.endswith((".xlsx", ".xlsm", ".xls")):
            sheets = pd.read_excel(io.BytesIO(raw), sheet_name=None, dtype=str)
            return list(sheets.values())
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("latin-1")
        return [pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False)]
    except Exception as e:  # noqa: BLE001 — any reader failure is a user-facing input problem
        raise InputError(f"Could not read the STTM sheet: {e}") from e


def parse_sttm(filename: str, raw: bytes) -> tuple[list[dict], str]:
    """Returns (rows, canonical_csv_text). Each row has every CANONICAL key plus `_row`."""
    frames = _read_frames(filename, raw)
    chosen, mapping = None, {}
    for df in frames:
        m = _map_headers([str(c) for c in df.columns])
        if all(k in m for k in _REQUIRED):
            chosen, mapping = df, m
            break
    if chosen is None:
        raise InputError("STTM sheet needs at least 'source_field' and 'target_field' columns "
                         "(aliases like 'Source Column' / 'Target Column' are accepted)")

    out = pd.DataFrame({canon: (chosen[mapping[canon]] if canon in mapping else "")
                        for canon in CANONICAL}).fillna("")

    rows = []
    for i, rec in enumerate(out.to_dict(orient="records")):
        clean = {}
        for k, v in rec.items():
            text = "" if str(v).strip().lower() in ("nan", "none") else str(v)
            # sample values keep their whitespace: "  John.DOE@Email.com " is the point of the sample
            clean[k] = text if k == "sample_data" else text.strip()
        clean["_row"] = i + 2  # header is spreadsheet row 1
        if clean["source_field"] or clean["target_field"]:
            rows.append(clean)
    if not rows:
        raise InputError("STTM sheet has no mapping rows")
    return rows, out.to_csv(index=False)

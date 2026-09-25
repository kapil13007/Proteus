"""One type vocabulary for every input.

Schemas arrive as Postgres-ish (VARCHAR), BigQuery (INT64) or generic (INTEGER)
names. Everything is reduced to a small set of families so the validator can
reason about compatibility, and each family maps back to one concrete type per
dialect (BigQuery for generated code, DuckDB for the local sandbox).
"""
import re

_FAMILY_BY_NAME = {
    "STRING": "string", "VARCHAR": "string", "CHAR": "string", "TEXT": "string",
    "NVARCHAR": "string", "CHARACTER VARYING": "string", "CHARACTER": "string",
    "INT64": "int", "INT": "int", "INTEGER": "int", "BIGINT": "int", "SMALLINT": "int",
    "TINYINT": "int", "BYTEINT": "int", "HUGEINT": "int", "UBIGINT": "int",
    "FLOAT64": "float", "FLOAT": "float", "DOUBLE": "float", "DOUBLE PRECISION": "float",
    "REAL": "float", "FLOAT4": "float", "FLOAT8": "float",
    "NUMERIC": "numeric", "DECIMAL": "numeric", "BIGNUMERIC": "numeric", "BIGDECIMAL": "numeric",
    "BOOL": "bool", "BOOLEAN": "bool",
    "DATE": "date",
    "DATETIME": "datetime", "TIMESTAMP WITHOUT TIME ZONE": "datetime",
    "TIMESTAMP": "timestamp", "TIMESTAMPTZ": "timestamp", "TIMESTAMP WITH TIME ZONE": "timestamp",
    "TIME": "time",
    "BYTES": "bytes", "BLOB": "bytes", "BYTEA": "bytes",
    "JSON": "json",
}

BIGQUERY_TYPE = {
    "string": "STRING", "int": "INT64", "float": "FLOAT64", "numeric": "NUMERIC",
    "bool": "BOOL", "date": "DATE", "datetime": "DATETIME", "timestamp": "TIMESTAMP",
    "time": "TIME", "bytes": "BYTES", "json": "JSON",
}

# Sandbox storage types. Timestamps are stored naive (UTC by session setting),
# which is how BigQuery TIMESTAMP values behave for this purpose.
DUCKDB_TYPE = {
    "string": "VARCHAR", "int": "BIGINT", "float": "DOUBLE", "numeric": "DECIMAL(38, 9)",
    "bool": "BOOLEAN", "date": "DATE", "datetime": "TIMESTAMP", "timestamp": "TIMESTAMP",
    "time": "TIME", "bytes": "BLOB", "json": "JSON",
}

# (source family, target family) pairs where a plain cast can lose or reject data.
LOSSY = {
    ("float", "int"), ("numeric", "int"), ("string", "int"), ("string", "float"),
    ("string", "numeric"), ("string", "date"), ("string", "datetime"), ("string", "timestamp"),
    ("string", "bool"), ("string", "time"), ("timestamp", "date"), ("datetime", "date"),
    ("float", "numeric"),
}

# Families that are interchangeable for "did the sandbox produce the right kind of value".
_COMPATIBLE = {
    ("int", "numeric"), ("int", "float"), ("numeric", "float"),
    ("datetime", "timestamp"), ("timestamp", "datetime"),
}


def base_name(type_name: str) -> str:
    """'VARCHAR(50)' -> 'VARCHAR', 'numeric(10, 2)' -> 'NUMERIC'."""
    return re.sub(r"\s*\(.*\)\s*$", "", str(type_name).strip()).upper()


def family(type_name: str) -> str:
    name = base_name(type_name)
    if name in _FAMILY_BY_NAME:
        return _FAMILY_BY_NAME[name]
    if name.startswith("DECIMAL") or name.startswith("NUMERIC"):
        return "numeric"
    if name.startswith("TIMESTAMP"):
        return "timestamp"
    if name.startswith(("STRUCT", "ARRAY", "LIST", "MAP", "RECORD")):
        return "other"
    return "other"


def bigquery_type(type_name: str) -> str:
    fam = family(type_name)
    return BIGQUERY_TYPE.get(fam, base_name(type_name))


def duckdb_type(type_name: str) -> str:
    fam = family(type_name)
    return DUCKDB_TYPE.get(fam, "VARCHAR")


def is_lossy(src_type: str, tgt_type: str) -> bool:
    return (family(src_type), family(tgt_type)) in LOSSY


def compatible(produced_family: str, target_family: str) -> bool:
    """Is a value of `produced_family` an acceptable input for the final CAST to the target?"""
    return produced_family == target_family or (produced_family, target_family) in _COMPATIBLE

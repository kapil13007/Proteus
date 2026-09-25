"""Source / target schema parser (markdown).

Header-driven, so column order and extra columns do not matter:

    # Table: raw.clinical_patients
    | column | type | nullable | key | description |
    |---|---|---|---|---|
    | patient_id | STRING | NO | PK | Unique patient identifier |

`nullable` accepts YES/NO/TRUE/FALSE, or BigQuery's `mode` column
(NULLABLE / REQUIRED) so a pasted `bq show --schema` table works too.
`key` is optional; PK / YES / TRUE / PRIMARY marks a key column, which becomes
a Dataform uniqueKey assertion and a local audit check.
"""
import re
from dataclasses import asdict, dataclass, field

from app.inputs import InputError
from app.inputs.types import family

_HEADER_ALIASES = {
    "name": {"column", "column_name", "name", "field", "field_name", "col"},
    "type": {"type", "data_type", "datatype", "column_type", "field_type"},
    "nullable": {"nullable", "null", "is_nullable", "nulls", "null_allowed"},
    "mode": {"mode"},
    "key": {"key", "pk", "primary_key", "is_key", "unique_key"},
    "description": {"description", "desc", "comment", "notes", "business_description"},
}


@dataclass
class ColumnDef:
    name: str
    type: str
    family: str
    nullable: bool = True
    key: bool = False
    description: str = ""


@dataclass
class TableSchema:
    table: str  # "dataset.name" — how the table is addressed in SQL
    dataset: str
    name: str
    columns: dict[str, ColumnDef] = field(default_factory=dict)
    project: str = ""

    def to_dict(self) -> dict:
        return {"table": self.table, "dataset": self.dataset, "name": self.name,
                "project": self.project,
                "columns": [asdict(c) for c in self.columns.values()]}

    @property
    def keys(self) -> list[str]:
        return [c.name for c in self.columns.values() if c.key]

    @property
    def required(self) -> list[str]:
        return [c.name for c in self.columns.values() if not c.nullable]


def _norm(h: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", h.strip().lower()).strip("_")


def _cells(line: str) -> list[str]:
    return [c.strip().strip("`") for c in line.strip().strip("|").split("|")]


def _is_separator(cells: list[str]) -> bool:
    return all(set(c) <= {"-", ":", " "} for c in cells) and any("-" in c for c in cells)


def _cell(cells: list[str], header: dict[str, int], key: str) -> str:
    i = header.get(key)
    return cells[i] if i is not None and i < len(cells) else ""


def _truthy(v: str) -> bool:
    return v.strip().upper() in {"YES", "Y", "TRUE", "T", "1", "NULLABLE", "PK", "PRIMARY", "KEY", "X"}


def _table_name(md: str) -> tuple[str, str, str]:
    m = re.search(r"^\s*#*\s*table\s*:\s*`?([\w.\-]+)`?", md, flags=re.IGNORECASE | re.MULTILINE)
    if not m:
        m = re.search(r"^\s*#+\s*`?([\w\-]+\.[\w\-]+(?:\.[\w\-]+)?)`?\s*$", md, flags=re.MULTILINE)
    if not m:
        raise InputError("Schema file must name its table, e.g. a first line '# Table: raw.clinical_patients'")
    parts = m.group(1).strip(".").split(".")
    if len(parts) == 1:
        raise InputError(f"Table '{parts[0]}' must be qualified with its dataset, e.g. raw.{parts[0]}")
    project = parts[-3] if len(parts) >= 3 else ""
    return project, parts[-2], parts[-1]


def parse_schema_md(md: str, role: str = "schema") -> TableSchema:
    project, dataset, name = _table_name(md)
    schema = TableSchema(table=f"{dataset}.{name}", dataset=dataset, name=name, project=project)

    header: dict[str, int] | None = None
    for raw in md.splitlines():
        line = raw.strip()
        if not line.startswith("|"):
            if header is not None and schema.columns:
                break  # first table ended
            continue
        cells = _cells(line)
        if header is None:
            normed = [_norm(c) for c in cells]
            found = {}
            for key, aliases in _HEADER_ALIASES.items():
                for i, h in enumerate(normed):
                    if h in aliases:
                        found[key] = i
                        break
            if "name" in found and "type" in found:
                header = found
            continue
        if _is_separator(cells):
            continue

        col_name, col_type = _cell(cells, header, "name"), _cell(cells, header, "type").upper()
        if not col_name:
            continue
        if not col_type:
            raise InputError(f"{role}: column '{col_name}' has no type")
        if col_name in schema.columns:
            raise InputError(f"{role}: column '{col_name}' is listed twice")
        nullable_cell = _cell(cells, header, "nullable")
        if "nullable" in header:
            nullable = _truthy(nullable_cell) if nullable_cell else True
        elif "mode" in header:
            nullable = _cell(cells, header, "mode").upper() != "REQUIRED"
        else:
            nullable = True
        schema.columns[col_name] = ColumnDef(
            name=col_name, type=col_type, family=family(col_type), nullable=nullable,
            key=_truthy(_cell(cells, header, "key")) if "key" in header else False,
            description=_cell(cells, header, "description"),
        )

    if header is None:
        raise InputError(f"{role}: no markdown table with 'column' and 'type' headers was found")
    if not schema.columns:
        raise InputError(f"{role}: the table for {schema.table} has no column rows")
    return schema

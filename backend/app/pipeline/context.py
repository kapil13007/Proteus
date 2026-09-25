"""RunContext: the parsed, validated inputs of one run, rebuilt from the stored uploads."""
import posixpath
from dataclasses import dataclass, field

from app.inputs.repo import RepoConventions, infer_conventions
from app.inputs.schema import TableSchema, parse_schema_md
from app.inputs.sttm import parse_sttm


@dataclass
class RunContext:
    run_id: str
    source: TableSchema
    target: TableSchema
    rows: list[dict]              # every STTM row (validation picks the active ones)
    conventions: RepoConventions
    functions_js: str = ""
    env_js: str = ""
    active_rows: list[dict] = field(default_factory=list)
    catalog: list[dict] = field(default_factory=list)
    env_values: dict = field(default_factory=dict)

    # -- how the generated SQLX reaches the team's includes ------------------------
    @property
    def functions_path(self) -> str:
        return self.conventions.functions_path

    @property
    def functions_name(self) -> str:
        return RepoConventions.global_name(self.functions_path) or \
            posixpath.basename(self.functions_path).rsplit(".", 1)[0]

    @property
    def functions_require(self) -> str | None:
        """Set when functions.js is nested (not global in Dataform), so SQLX must require() it."""
        if RepoConventions.global_name(self.functions_path):
            return None
        return RepoConventions.module_path(self.functions_path)

    @property
    def env_path(self) -> str:
        return self.conventions.env_vars_path

    @property
    def env_name(self) -> str | None:
        """Global name of the env-vars include, if it is a top-level include."""
        return RepoConventions.global_name(self.env_path) if self.env_js else None

    def includes(self) -> dict[str, str]:
        inc = {}
        if self.functions_js:
            inc[self.functions_path] = self.functions_js
        if self.env_js:
            inc[self.env_path] = self.env_js
        return inc

    def globals(self) -> dict[str, str]:
        g = {}
        if self.functions_js and not self.functions_require:
            g[self.functions_name] = self.functions_path
        if self.env_name:
            g[self.env_name] = self.env_path
        return g


def build_context(run_id: str, inputs: dict) -> RunContext:
    """Parse the stored uploads. Raises InputError with a user-facing message."""
    rows, _ = parse_sttm("sttm.csv", inputs["sttm_csv"].encode("utf-8"))
    return RunContext(
        run_id=run_id,
        source=parse_schema_md(inputs["source_schema_md"], "source schema"),
        target=parse_schema_md(inputs["target_schema_md"], "target schema"),
        rows=rows,
        conventions=infer_conventions(inputs.get("repo_structure_md", "")),
        functions_js=inputs.get("functions_js", ""),
        env_js=inputs.get("env_vars_js", ""),
    )

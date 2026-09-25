"""Folder-structure parser: turns the team's repo layout into concrete file paths.

The input is the markdown the team already has: a `tree` listing (unicode,
Windows `tree /F`, or an indented bullet list) and/or plain paths in prose.
Nothing here calls the LLM. Conventions are inferred from the examples in the
tree ("dim_sites/ contains dim_sites_read.sqlx, so a new table T gets
T_read.sqlx"), and every inference is recorded as evidence the reviewer can see.
"""
import posixpath
import re
from dataclasses import asdict, dataclass, field

_FILE_EXT = re.compile(r"\.[A-Za-z0-9]{1,6}$")
_STEP_WORDS = {
    "read": ("read", "extract", "source"),
    "process": ("process", "transform", "proc", "logic"),
    "write": ("write", "load", "final", "publish"),
}


@dataclass
class RepoConventions:
    layer_dir: str = "definitions/gold"
    table_subdir: bool = True  # each table gets its own folder inside the layer
    step_files: dict = field(default_factory=lambda: {
        "read": "{table}_read.sqlx", "process": "{table}_process.sqlx", "write": "{table}_write.sqlx"})
    functions_path: str = "includes/functions.js"
    env_vars_path: str = "includes/env_vars.js"
    source_params_dir: str = "includes/params/source_table"
    target_params_dir: str = "includes/params/target_table"
    params_file: str = "{table}.js"
    declarations_dir: str = "definitions/sources"
    declaration_file: str = "{table}.sqlx"
    existing_paths: list = field(default_factory=list)
    evidence: list = field(default_factory=list)

    # -- paths for generated files -------------------------------------------
    def step_path(self, step: str, table: str) -> str:
        name = self.step_files[step].format(table=table)
        folder = f"{self.layer_dir}/{table}" if self.table_subdir else self.layer_dir
        return f"{folder}/{name}"

    def source_params_path(self, table: str) -> str:
        return f"{self.source_params_dir}/{self.params_file.format(table=table)}"

    def target_params_path(self, table: str) -> str:
        return f"{self.target_params_dir}/{self.params_file.format(table=table)}"

    def declaration_path(self, table: str) -> str:
        return f"{self.declarations_dir}/{self.declaration_file.format(table=table)}"

    def existing_declaration(self, table: str) -> str | None:
        """A .sqlx under definitions/ already named after the source table (not in the gold layer)."""
        for p in self.existing_paths:
            if (p.startswith("definitions/") and p.endswith(f"/{table}.sqlx")
                    and not p.startswith(self.layer_dir + "/")):
                return p
        return None

    # -- how generated SQLX reaches the includes ------------------------------
    @staticmethod
    def global_name(path: str) -> str | None:
        """Dataform exposes only top-level includes/*.js files as globals (by file name)."""
        parts = path.split("/")
        if len(parts) == 2 and parts[0] == "includes" and parts[1].endswith(".js"):
            return parts[1][:-3]
        return None

    @staticmethod
    def module_path(path: str) -> str:
        """require() path for an include: project-relative, without .js."""
        return path[:-3] if path.endswith(".js") else path

    def to_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------- #
#  Tree / path-list parsing
# --------------------------------------------------------------------------- #

_PREFIX = re.compile(r"^([\s│├└─┬┼┆┊╰╭┝┕|+\\`'*•·-]*)(.*)$")
_COMMENT_SPLIT = re.compile(r"\s+(#|//|--|—|–|<-|←|\()\s*")
_INLINE_PATH = re.compile(r"`?((?:definitions|includes)(?:/[\w.\-{}]+)+/?)`?")


def _is_file(name: str) -> bool:
    return bool(_FILE_EXT.search(name)) or name.startswith(".")


def _candidate_lines(text: str) -> tuple[list[str], list[str]]:
    """(tree lines, prose lines). Tree lines are the fenced blocks — or every line if there are none."""
    inside, outside, in_fence = [], [], False
    for line in text.splitlines():
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        (inside if in_fence else outside).append(line)
    return (inside or outside), outside


def _strip_wrapping_root(paths: set[str]) -> set[str]:
    """Drop a repo-name folder (e.g. 'dataform-models/') that wraps definitions/ and includes/."""
    roots = set()
    for p in paths:
        parts = p.split("/")
        for i in range(1, len(parts)):
            if parts[i].lower() in ("definitions", "includes"):
                roots.add("/".join(parts[:i]))
                break
    if len(roots) != 1:
        return paths
    root = next(iter(roots))
    kept = set()
    for p in paths:
        if p == root:
            continue
        kept.add(p[len(root) + 1:] if p.startswith(root + "/") else p)
    return kept


def parse_tree(text: str) -> list[str]:
    """All paths (files and directories, '/'-separated, no trailing slash) mentioned in the text."""
    tree_lines, prose_lines = _candidate_lines(text)
    paths: set[str] = set()
    stack: list[tuple[int, str]] = []  # (indent, dir path)

    for line in tree_lines:
        if not line.strip():
            continue
        m = _PREFIX.match(line.rstrip())
        indent, rest = len(m.group(1)), m.group(2)
        name = _COMMENT_SPLIT.split(rest, maxsplit=1)[0].strip().strip("`").strip()
        if not name or name in (".", "./") or name.startswith("#"):
            stack = []
            continue
        if " " in name.rstrip("/"):
            continue  # prose, not a path
        is_dir = name.endswith("/") or not _is_file(name.split("/")[-1])
        name = name.strip("/")
        while stack and stack[-1][0] >= indent:
            stack.pop()
        parent = stack[-1][1] if stack else ""
        full = f"{parent}/{name}" if parent else name
        paths.add(full)
        if is_dir:
            stack.append((indent, full))

    for line in prose_lines:
        for m in _INLINE_PATH.finditer(line):
            paths.add(m.group(1).strip("/"))

    paths = _strip_wrapping_root(paths)
    for p in list(paths):  # every parent directory is a path too
        parts = p.split("/")
        for i in range(1, len(parts)):
            paths.add("/".join(parts[:i]))
    return sorted(paths)


# --------------------------------------------------------------------------- #
#  Convention inference
# --------------------------------------------------------------------------- #

def _pick(files: list[str], names: tuple[str, ...]) -> str | None:
    for wanted in names:
        for f in files:
            if posixpath.basename(f).lower() == wanted:
                return f
    return None


def _children(paths: list[str], parent: str) -> list[str]:
    prefix = parent + "/"
    return [p for p in paths if p.startswith(prefix) and "/" not in p[len(prefix):]]


def _step_of(filename: str) -> str | None:
    stem = filename.lower().rsplit(".", 1)[0]
    tokens = set(re.split(r"[_\-.]", stem))
    for step, words in _STEP_WORDS.items():
        if tokens & set(words):
            return step
    return None


def infer_conventions(text: str) -> RepoConventions:
    conv = RepoConventions()
    paths = parse_tree(text or "")
    conv.existing_paths = paths
    ev = conv.evidence
    if not paths:
        ev.append("No folder tree found — using the default Dataform gold-layer layout.")
        return conv
    files = [p for p in paths if _is_file(posixpath.basename(p))]
    dirs = [p for p in paths if p not in files]

    # UDF + environment files
    fn = _pick(files, ("functions.js", "udfs.js", "udf.js", "macros.js", "helpers.js"))
    if fn:
        conv.functions_path = fn
        ev.append(f"UDF library: {fn}")
    else:
        ev.append("No functions.js in the tree — assuming includes/functions.js.")
    env = _pick(files, ("env_vars.js", "env.js", "environment.js", "constants.js", "vars.js"))
    if env:
        conv.env_vars_path = env
        ev.append(f"Environment variables: {env}")

    # Layer folder (Kimball gold layer)
    layer = next((d for d in sorted(dirs, key=len) if posixpath.basename(d).lower() == "gold"), None)
    if not layer:
        layer = next((d for d in sorted(dirs, key=len)
                      if posixpath.basename(d).lower() in ("marts", "mart", "presentation", "curated")), None)
        if layer:
            ev.append(f"No 'gold' folder — using {layer} as the target layer.")
    if layer:
        conv.layer_dir = layer
        ev.append(f"Target layer folder: {layer}/")
    else:
        ev.append("No gold/marts folder in the tree — using definitions/gold/.")

    # read / process / write naming, learned from an existing table in the layer
    learned = False
    for table_dir in sorted(d for d in dirs if posixpath.dirname(d) == conv.layer_dir):
        table = posixpath.basename(table_dir)
        steps = {}
        for f in _children(files, table_dir):
            base = posixpath.basename(f)
            step = _step_of(base) if base.endswith(".sqlx") else None
            if step and step not in steps:
                steps[step] = base.replace(table, "{table}")
        if len(steps) >= 2:
            conv.step_files.update(steps)
            conv.table_subdir = True
            learned = True
            ev.append(f"Step files learned from {table_dir}/: "
                      + ", ".join(f"{k} → {v}" for k, v in steps.items()))
            break
    if not learned:
        flat = {}
        for f in _children(files, conv.layer_dir):
            step = _step_of(posixpath.basename(f)) if f.endswith(".sqlx") else None
            if step:
                flat.setdefault(step, f)
        if flat:
            conv.table_subdir = False
            ev.append(f"Layer keeps step files flat (e.g. {next(iter(flat.values()))}); no per-table folders.")
        else:
            ev.append("No existing table in the layer to learn from — using {table}/{table}_read|process|write.sqlx.")

    # params/<source>/, params/<target>/
    params = next((d for d in sorted(dirs, key=len)
                   if posixpath.basename(d).lower() in ("params", "parameters")), None)
    if params:
        subs = [d for d in dirs if posixpath.dirname(d) == params]
        src = next((d for d in subs if re.search(r"source|src", posixpath.basename(d), re.I)), None)
        tgt = next((d for d in subs if re.search(r"target|tgt|dest", posixpath.basename(d), re.I)), None)
        conv.source_params_dir = src or f"{params}/source_table"
        conv.target_params_dir = tgt or f"{params}/target_table"
        ev.append(f"Table parameters: {conv.source_params_dir}/ and {conv.target_params_dir}/")
        gold_tables = {posixpath.basename(d) for d in dirs if posixpath.dirname(d) == conv.layer_dir}
        for f in _children(files, conv.target_params_dir):
            stem = posixpath.basename(f)
            for t in gold_tables:
                if t in stem:
                    conv.params_file = stem.replace(t, "{table}")
                    break
    else:
        ev.append("No params/ folder in the tree — using includes/params/source_table|target_table/.")

    # Source declarations
    decl = next((d for d in sorted(dirs, key=len)
                 if d.startswith("definitions/")
                 and posixpath.basename(d).lower() in ("sources", "source", "declarations", "raw")), None)
    if decl:
        conv.declarations_dir = decl
        ev.append(f"Source declarations: {decl}/")
    return conv

"""Compile Dataform SQLX locally, the way `dataform compile` does.

A SQLX file is: a `config { ... }` JS object, optional `js { ... }` blocks that
define locals, and a SQL body whose `${...}` pieces are JavaScript evaluated
with the project's includes in scope. So `${functions.cleanEmail("email")}`
becomes whatever the team's functions.js returns — the UDF call is verified by
running the team's real code, not a guess about what it does.

JS runs in an embedded V8 isolate (mini-racer). A DataformProject is a context
manager: V8 is started once per pipeline stage and always closed (an unclosed
isolate would keep the Python process from exiting).
"""
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from py_mini_racer import MiniRacer

from app.dataform import CompileError

_RUNTIME_JS = (Path(__file__).parent / "runtime.js").read_text(encoding="utf-8")
_EVAL_TIMEOUT_SEC = 2.0
_MAX_MEMORY = 128 * 1024 * 1024


# --------------------------------------------------------------------------- #
#  Text scanning: find ${...} expressions and top-level { } blocks safely
# --------------------------------------------------------------------------- #

def _skip_string(s: str, i: int) -> int:
    quote, i = s[i], i + 1
    while i < len(s):
        if s[i] == "\\":
            i += 2
            continue
        if s[i] == quote:
            return i + 1
        i += 1
    raise CompileError("unterminated string literal")


def _skip_template_literal(s: str, i: int) -> int:
    i += 1
    while i < len(s):
        if s[i] == "\\":
            i += 2
            continue
        if s[i] == "`":
            return i + 1
        if s.startswith("${", i):
            i = _match_brace(s, i + 1) + 1
            continue
        i += 1
    raise CompileError("unterminated template literal")


def _match_brace(s: str, i: int) -> int:
    """s[i] == '{'. Returns the index of the matching '}', skipping JS strings."""
    depth = 0
    while i < len(s):
        c = s[i]
        if c in "'\"":
            i = _skip_string(s, i)
            continue
        if c == "`":
            i = _skip_template_literal(s, i)
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    raise CompileError("unbalanced braces")


def split_template(text: str) -> list[tuple[str, str]]:
    """'a ${x} b' -> [('lit', 'a '), ('expr', 'x'), ('lit', ' b')]."""
    parts, buf, i = [], [], 0
    while i < len(text):
        if text.startswith("${", i):
            end = _match_brace(text, i + 1)
            parts.append(("lit", "".join(buf)))
            parts.append(("expr", text[i + 2:end]))
            buf, i = [], end + 1
        else:
            buf.append(text[i])
            i += 1
    parts.append(("lit", "".join(buf)))
    return parts


def _template_js(text: str) -> str:
    """JS expression producing the rendered text. Literals are JSON-encoded, so SQL
    backticks and backslashes need no escaping (a classic template-literal pitfall)."""
    pieces = [json.dumps(v) if kind == "lit" else f"String({v})" for kind, v in split_template(text)]
    return "[" + ",".join(pieces) + "].join('')"


@dataclass
class SqlxParts:
    config: str = "{}"
    js: list[str] = field(default_factory=list)
    body: str = ""


_BLOCK_START = re.compile(r"(config|js|pre_operations|post_operations)\s*\{")


def split_sqlx(text: str) -> SqlxParts:
    """Pull config/js/operations blocks out of a SQLX file; the rest is the SQL body."""
    parts, body, i = SqlxParts(), [], 0
    while i < len(text):
        m = _BLOCK_START.match(text, i)
        at_line_start = text[text.rfind("\n", 0, i) + 1:i].strip() == ""
        if m and at_line_start:
            brace = m.end() - 1
            end = _match_brace(text, brace)
            kind = m.group(1)
            if kind == "config":
                parts.config = text[brace:end + 1]
            elif kind == "js":
                parts.js.append(text[brace + 1:end])
            i = end + 1  # operations blocks are not part of the SELECT we verify
            continue
        body.append(text[i])
        i += 1
    parts.body = "".join(body).strip()
    return parts


# --------------------------------------------------------------------------- #
#  UDF documentation (JSDoc / line comments above each function)
# --------------------------------------------------------------------------- #

_DOC_BEFORE_FN = re.compile(
    r"(?:/\*\*(?P<block>.*?)\*/|(?P<lines>(?:[ \t]*//[^\n]*\n)+))\s*"
    r"(?:export\s+)?(?:async\s+)?(?:function\s+(?P<fn>[A-Za-z_$][\w$]*)"
    r"|(?:const|let|var)\s+(?P<var>[A-Za-z_$][\w$]*)\s*=)",
    re.DOTALL,
)


def udf_docs(source: str) -> dict[str, str]:
    docs = {}
    for m in _DOC_BEFORE_FN.finditer(source):
        name = m.group("fn") or m.group("var")
        raw = m.group("block") or re.sub(r"^[ \t]*//", "", m.group("lines") or "", flags=re.MULTILINE)
        text = " ".join(line.strip(" *\t") for line in raw.splitlines())
        text = re.split(r"\s@\w+", " " + text)[0].strip()  # drop @param/@returns tags
        if text:
            docs[name] = text
    return docs


# --------------------------------------------------------------------------- #
#  The project: includes + a V8 isolate
# --------------------------------------------------------------------------- #

@dataclass
class CompiledAction:
    name: str
    type: str
    schema: str
    config: dict
    sql: str


class DataformProject:
    def __init__(self, includes: dict[str, str], globals_: dict[str, str]):
        """includes: project path -> JS source. globals_: global name -> include path."""
        self._includes = dict(includes)
        self._globals = dict(globals_)
        self._js: MiniRacer | None = None

    def __enter__(self) -> "DataformProject":
        self._js = MiniRacer()
        try:
            self._eval(_RUNTIME_JS)
            for path, src in self._includes.items():
                self._define(path, src)
            for name, path in self._globals.items():
                try:
                    self._eval(f"__global({json.dumps(name)}, {json.dumps(path)})")
                except CompileError as e:
                    raise CompileError(f"{path} failed to load: {e}") from e
        except BaseException:
            self.close()
            raise
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        if self._js is not None:
            self._js.close()
            self._js = None

    # -- low level -------------------------------------------------------------
    def _eval(self, code: str):
        if self._js is None:
            raise RuntimeError("DataformProject used outside its `with` block")
        try:
            return self._js.eval(code, timeout_sec=_EVAL_TIMEOUT_SEC, max_memory=_MAX_MEMORY)
        except Exception as e:  # noqa: BLE001 — JS errors, timeouts and OOM all surface the same way
            msg = str(e).strip().splitlines()
            text = next((ln for ln in msg if "Error" in ln or "error" in ln), msg[0] if msg else repr(e))
            text = re.sub(r"^(<anonymous>|undefined):\d+:\s*", "", text.strip())
            raise CompileError(re.sub(r"^Error:\s*", "", text)) from e

    def _define(self, path: str, source: str) -> None:
        self._eval(f"__define({json.dumps(path)}, {json.dumps(source)})")

    def define(self, path: str, source: str) -> None:
        """Add or replace an include (e.g. regenerated params files)."""
        self._includes[path] = source
        self._define(path, source)

    def set_refs(self, refs: dict[str, str], self_name: str = "") -> None:
        self._eval(f"__setRefs({json.dumps(json.dumps(refs))}, {json.dumps(self_name)})")

    # -- includes introspection -------------------------------------------------
    def udf_catalog(self, path: str) -> list[dict]:
        """Every exported function of the UDF library: name, params, the SQL it expands to, its doc."""
        entries = json.loads(self._eval(f"__catalog({json.dumps(path)})"))
        docs = udf_docs(self._includes.get(path, ""))
        for e in entries:
            e["description"] = docs.get(e["name"], "")
            e["kind"] = "column" if e["example"] else "table"
        return entries

    def module_values(self, path: str) -> dict:
        """Primitive values an include exports (e.g. env_vars.js dataset names)."""
        return json.loads(self._eval(f"__moduleValues({json.dumps(path)})"))

    # -- expression templates (one V8 round trip for a whole batch) -------------
    def expand(self, templates: list[str], locals_js: str = "") -> list[dict]:
        items = []
        for t in templates:
            try:
                expr = _template_js(t)
            except CompileError as e:
                items.append(json.dumps({"ok": False, "error": str(e)}))
                continue
            items.append("(function(){try{" + locals_js + ";return {ok:true,sql:" + expr + "};}"
                         "catch(e){return {ok:false,error:String(e&&e.message?e.message:e)};}})()")
        if not items:
            return []
        return json.loads(self._eval("JSON.stringify([" + ",".join(items) + "])"))

    # -- SQLX files --------------------------------------------------------------
    def read_config(self, text: str, default_name: str) -> dict:
        parts = split_sqlx(text)
        locals_js = ";".join(parts.js)
        raw = self._eval("(function(){" + locals_js + ";return JSON.stringify((" + parts.config + "));})()")
        config = json.loads(raw)
        config.setdefault("name", default_name)
        config.setdefault("type", "table")
        return config

    def compile_body(self, text: str, self_name: str = "") -> str:
        parts = split_sqlx(text)
        locals_js = ";".join(parts.js)
        self._eval(f"__self = {json.dumps(self_name)}")
        return self._eval("(function(){" + locals_js + ";return " + _template_js(parts.body) + ";})()")

    def compile_file(self, text: str, default_name: str) -> CompiledAction:
        config = self.read_config(text, default_name)
        sql = self.compile_body(text, config["name"])
        return CompiledAction(name=config["name"], type=config["type"],
                              schema=config.get("schema", ""), config=config, sql=sql)


def strip_sql_comments(sql: str) -> str:
    """Drop `--` line comments (outside quotes) so compiled SQL can be nested safely."""
    out, i, n = [], 0, len(sql)
    while i < n:
        c = sql[i]
        if c in "'\"`":
            j = i + 1
            while j < n and sql[j] != c:
                j += 2 if sql[j] == "\\" else 1
            out.append(sql[i:j + 1])
            i = j + 1
            continue
        if sql.startswith("--", i):
            while i < n and sql[i] != "\n":
                i += 1
            continue
        out.append(c)
        i += 1
    return "".join(out)

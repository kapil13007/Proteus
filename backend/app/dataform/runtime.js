// Mapfl0w's miniature Dataform compile runtime.
//
// Loaded into an embedded V8 isolate (mini-racer) — the same JavaScript engine
// Dataform's own compiler runs on. It reproduces exactly the pieces of Dataform
// compilation that generated SQLX relies on:
//   * CommonJS includes (module.exports / require) — functions.js, env_vars.js, params/*.js
//   * top-level includes/*.js exposed as globals by file name
//   * ref() / resolve() / self() / when() / incremental()
// The isolate has no filesystem or network access, and every eval runs under a
// timeout, so evaluating an uploaded functions.js is safe.

var __modules = Object.create(null); // normalised path -> source text
var __exports = Object.create(null); // normalised path -> module.exports
var __refs = Object.create(null); // action name -> SQL table reference
var __self = "";
var dataform = { projectConfig: { vars: {}, defaultSchema: "", defaultDatabase: "" } };

function __norm(p) {
  return String(p).replace(/\\/g, "/").replace(/^(\.\/)+/, "").replace(/\.js$/, "");
}

function __define(path, source) {
  var key = __norm(path);
  __modules[key] = source;
  delete __exports[key];
}

function require(path) {
  var key = __norm(path);
  if (key in __exports) return __exports[key];
  if (!(key in __modules)) throw new Error('require("' + path + '"): no such include');
  var module = { exports: {} };
  __exports[key] = module.exports; // tolerate require cycles like Node does
  new Function("module", "exports", "require", __modules[key])(module, module.exports, require);
  __exports[key] = module.exports;
  return module.exports;
}

function __global(name, path) {
  globalThis[name] = require(path);
}

function __setRefs(json, selfName) {
  __refs = JSON.parse(json);
  __self = selfName || "";
}

function ref() {
  var a = arguments;
  var target = a.length === 1 && a[0] !== null && typeof a[0] === "object" ? a[0].name : a[a.length - 1];
  if (!(target in __refs)) {
    throw new Error('ref("' + target + '") does not match a declared source or a generated action');
  }
  return __refs[target];
}
var resolve = ref;
function self() { return __self; }
function when(cond, a, b) { return cond ? a : (b === undefined ? "" : b); }
function incremental() { return false; }

// ---------------------------------------------------------------------------
// UDF catalog: what each exported function is called, what it takes, and the
// SQL it expands to. Calling a function with its own parameter names as
// arguments shows its semantics compactly: cleanEmail(col) -> LOWER(TRIM(col)).
// ---------------------------------------------------------------------------

function __splitTopLevel(s) {
  var out = [], depth = 0, cur = "", q = null;
  for (var i = 0; i < s.length; i++) {
    var c = s[i];
    if (q) {
      cur += c;
      if (c === "\\") { cur += s[++i] || ""; continue; }
      if (c === q) q = null;
      continue;
    }
    if (c === "'" || c === '"' || c === "`") { q = c; cur += c; continue; }
    if ("([{".indexOf(c) >= 0) depth++;
    if (")]}".indexOf(c) >= 0) depth--;
    if (c === "," && depth === 0) { out.push(cur); cur = ""; continue; }
    cur += c;
  }
  if (cur.trim()) out.push(cur);
  return out;
}

function __params(fn) {
  var src = Function.prototype.toString.call(fn).trim();
  var list;
  var arrowNoParens = src.match(/^(?:async\s+)?([A-Za-z_$][\w$]*)\s*=>/);
  if (arrowNoParens) {
    list = arrowNoParens[1];
  } else {
    var open = src.indexOf("(");
    if (open < 0) return [];
    var depth = 0, end = -1, q = null;
    for (var i = open; i < src.length; i++) {
      var c = src[i];
      if (q) { if (c === "\\") { i++; continue; } if (c === q) q = null; continue; }
      if (c === "'" || c === '"' || c === "`") { q = c; continue; }
      if (c === "(") depth++;
      if (c === ")") { depth--; if (depth === 0) { end = i; break; } }
    }
    list = src.slice(open + 1, end);
  }
  return __splitTopLevel(list).map(function (p) {
    var eq = p.indexOf("=");
    var name = (eq >= 0 ? p.slice(0, eq) : p).trim();
    var dflt = eq >= 0 ? p.slice(eq + 1).trim() : null;
    return { name: name, default: dflt };
  }).filter(function (p) { return p.name.length > 0; });
}

function __moduleValues(path) {
  var mod = require(path) || {};
  var out = {};
  Object.keys(mod).forEach(function (k) {
    var v = mod[k];
    if (typeof v === "string" || typeof v === "number" || typeof v === "boolean") out[k] = v;
  });
  return JSON.stringify(out);
}

function __catalog(path) {
  var mod = require(path);
  var out = [];
  if (!mod || typeof mod !== "object") return JSON.stringify(out);
  Object.keys(mod).forEach(function (key) {
    var fn = mod[key];
    if (typeof fn !== "function") return;
    var params = __params(fn);
    var args = params.slice(0, fn.length).map(function (p) { return p.name; });
    var example = null, error = null;
    try {
      var r = fn.apply(null, args);
      if (typeof r === "string") example = r;
      else error = "returns " + typeof r + ", not SQL text";
    } catch (e) {
      error = String(e && e.message ? e.message : e);
    }
    out.push({ name: key, arity: fn.length, params: params, example: example, error: error });
  });
  return JSON.stringify(out);
}

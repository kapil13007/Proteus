// includes/functions.js — the team's reusable SQL snippets (Dataform includes).
// Each column-level function returns BigQuery SQL for one expression, so every
// table cleans emails, parses dates and resolves sites the same reviewed way.

/**
 * Standardised e-mail cleaning: trims whitespace and lower-cases.
 * @param {string} col column or SQL expression
 */
function cleanEmail(col) {
  return `LOWER(TRIM(${col}))`;
}

/** Joins first and last name with one space; NULL when both parts are empty. */
function fullName(first, last) {
  return `NULLIF(TRIM(CONCAT(COALESCE(${first}, ''), ' ', COALESCE(${last}, ''))), '')`;
}

/** Parses a date string in the given format; unparseable values become NULL instead of failing the load. */
function safeParseDate(col, format = "%Y-%m-%d") {
  return `SAFE.PARSE_DATE('${format}', ${col})`;
}

/** Maps trial site codes to city names: 01=Chennai, 02=Mumbai, 03=Delhi, anything else=Unknown. */
function siteLookup(code) {
  return `CASE ${code} WHEN '01' THEN 'Chennai' WHEN '02' THEN 'Mumbai' WHEN '03' THEN 'Delhi' ELSE 'Unknown' END`;
}

/** Converts a Y/N flag to BOOL, tolerating case and padding. */
function ynToBool(col) {
  return `(UPPER(TRIM(${col})) = 'Y')`;
}

/** Table-level helper: comma-separated column list from a params object. */
function columnList(params) {
  return params.columns.join(",\n  ");
}

module.exports = { cleanEmail, fullName, safeParseDate, siteLookup, ynToBool, columnList };

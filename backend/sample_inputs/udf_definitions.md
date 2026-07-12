# Dataform UDF Definitions

## cleanEmail(col)
- File: includes/macros.js
- Purpose: TRIM(LOWER(col)) — standardized email cleaning
- When to use: any email field transformation
- Example: ${helpers.cleanEmail("raw_email")}

## siteLookup(code)
- File: includes/macros.js
- Purpose: Maps trial site codes to city names (01=Chennai, 02=Mumbai, 03=Delhi)
- When to use: any site_code mapping

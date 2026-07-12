# Dataform repo structure

## Folder conventions
- definitions/staging/ — raw source models, prefix: stg_
- definitions/marts/ — final target tables, prefix: fct_ or dim_

## Naming conventions
- Target tables live in schema "analytics"
- File name = target table name in snake_case

## Config defaults
- type: table
- schema: "analytics"
- tags: ["daily"]

## Notes
- All mart models must include a _loaded_at column
- Never write LOWER() inline for emails — use cleanEmail() semantics

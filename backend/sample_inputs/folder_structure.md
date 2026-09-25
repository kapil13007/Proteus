# Dataform repository structure

Medallion layout; the gold layer follows Kimball (facts and dimensions). Every
gold table gets its own folder holding three steps: **read** (project the
source), **process** (apply the STTM business rules with our UDFs) and
**write** (cast to the target contract and materialise the table).

```text
dataform-models/
├── workflow_settings.yaml
├── definitions/
│   ├── sources/
│   │   └── sites.sqlx                  # declaration of raw.sites
│   └── gold/
│       └── dim_sites/
│           ├── dim_sites_read.sqlx
│           ├── dim_sites_process.sqlx
│           └── dim_sites_write.sqlx
└── includes/
    ├── functions.js                    # team UDFs (reviewed, cost-optimised)
    ├── env_vars.js                     # per-environment settings
    └── params/
        ├── source_table/
        │   └── sites.js                # parameters for the source table
        └── target_table/
            └── dim_sites.js            # parameters for the target table
```

## Conventions
- Reference tables only through `ref()`; raw tables are declared under `definitions/sources/`.
- UDFs from `includes/functions.js` are preferred over hand-written SQL.
- Dataset names come from `includes/env_vars.js`, never hard-coded per environment.

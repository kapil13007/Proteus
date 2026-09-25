# Table: analytics.fct_clinical_patients

Gold-layer patient fact consumed by the Power BI / Tableau clinical dashboards.

| column | type | nullable | key | description |
|---|---|---|---|---|
| patient_id | STRING | NO | PK | Unique patient identifier |
| full_name | STRING | YES | | First and last name |
| email_address | STRING | YES | | Cleaned, lower-case email |
| date_of_birth | DATE | YES | | Parsed date of birth |
| weight | INT64 | YES | | Weight rounded to whole kilograms |
| site_city | STRING | NO | | City of the trial site |
| is_enrolled | BOOL | YES | | Enrollment flag |
| visit_count | INT64 | YES | | Number of visits |
| created_ts | TIMESTAMP | YES | | Source record creation time |
| _loaded_at | TIMESTAMP | NO | | Load timestamp |

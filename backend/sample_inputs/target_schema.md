# Table: analytics.fct_clinical_patients

| column | type | nullable | description |
|---|---|---|---|
| patient_id | VARCHAR | NO | Unique patient identifier |
| full_name | VARCHAR | YES | first + last name |
| email_address | VARCHAR | YES | Cleaned email |
| date_of_birth | DATE | YES | Parsed date of birth |
| weight | INTEGER | YES | Weight rounded to integer kg |
| site_city | VARCHAR | YES | City resolved from site_code |
| is_enrolled | BOOLEAN | YES | Enrollment flag as boolean |
| _loaded_at | TIMESTAMP | NO | Load timestamp |

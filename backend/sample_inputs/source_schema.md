# Table: raw.clinical_patients

Raw patient extract as landed by ingestion. Nothing is cleaned yet.

| column | type | nullable | description |
|---|---|---|---|
| patient_id | STRING | NO | Unique patient identifier |
| first_name | STRING | YES | Patient first name |
| last_name | STRING | YES | Patient last name |
| cust_email_01 | STRING | YES | Raw email, inconsistent casing and whitespace |
| dob | STRING | YES | Date of birth: ISO-8601 (YYYY-MM-DD), legacy rows use DD/MM/YYYY |
| weight_kg | FLOAT64 | YES | Weight in kilograms |
| site_code | STRING | YES | Trial site code: 01, 02, 03 |
| enrolled_flag | STRING | YES | Enrollment flag, Y or N with inconsistent casing |
| visit_count | STRING | YES | Number of visits, stored as text |
| created_at | TIMESTAMP | YES | Record creation time in the source system |
| raw_payload | STRING | YES | Original ingestion record (JSON), kept for audit |

# Table: raw.clinical_patients

| column | type | nullable | description |
|---|---|---|---|
| patient_id | VARCHAR | NO | Unique patient identifier |
| first_name | VARCHAR | YES | Patient first name |
| last_name | VARCHAR | YES | Patient last name |
| cust_email_01 | VARCHAR | YES | Raw email, inconsistent casing/whitespace |
| dob | VARCHAR | YES | Date of birth as ISO-8601 string |
| weight_kg | FLOAT | YES | Weight in kilograms |
| site_code | VARCHAR | YES | Trial site code: 01, 02, 03 |
| enrolled_flag | VARCHAR | YES | 'Y' or 'N' |
| created_at | TIMESTAMP | YES | Record creation time |

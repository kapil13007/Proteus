-- Demo source data for the local DuckDB warehouse (runs once, on first start).
-- Deliberately dirty, like real raw data: padded / mixed-case emails, legacy
-- DD/MM/YYYY dates, unknown site codes, free-text flags and counts. The target
-- table is NOT created here — the pipeline creates it (CREATE OR REPLACE TABLE AS SELECT).
CREATE SCHEMA IF NOT EXISTS raw;

CREATE TABLE raw.clinical_patients (
    patient_id      VARCHAR NOT NULL,
    first_name      VARCHAR,
    last_name       VARCHAR,
    cust_email_01   VARCHAR,
    dob             VARCHAR,     -- ISO-8601 mostly; legacy rows use DD/MM/YYYY
    weight_kg       DOUBLE,
    site_code       VARCHAR,     -- '01' | '02' | '03' (anything else is unknown)
    enrolled_flag   VARCHAR,     -- 'Y' / 'N', inconsistent casing
    visit_count     VARCHAR,     -- numbers stored as text
    created_at      TIMESTAMP,
    raw_payload     VARCHAR      -- original ingestion record (JSON); big, and no mapping uses it
);

INSERT INTO raw.clinical_patients
  (patient_id, first_name, last_name, cust_email_01, dob, weight_kg, site_code, enrolled_flag, visit_count, created_at)
VALUES
 ('P-0001', 'John',    'Doe',     '  John.DOE@Email.com ',  '1985-03-14', 82.4, '01', 'Y',  '3',   '2026-06-01 09:15:00'),
 ('P-0002', 'Priya',   'Sharma',  'priya.sharma@email.com', '1992-11-02', 61.0, '02', 'Y',  '12',  '2026-06-01 10:20:00'),
 ('P-0003', 'Arun',    'Kumar',   'ARUN.K@email.com',       '23/07/1978', NULL, '03', 'N',  '1',   '2026-06-02 08:05:00'),
 ('P-0004', 'Meera',   'Iyer',    NULL,                     '1989-01-30', 55.6, '01', 'y ', '',    '2026-06-02 12:40:00'),
 ('P-0005', 'David',   'Lee',     'david.lee@email.com ',   '1995-09-17', 70.2, '02', 'Y',  '7',   '2026-06-03 09:00:00'),
 ('P-0006', 'Sara',    'Khan',    'sara.khan@Email.com',    '08/05/1983', 68.9, '03', 'N',  'n/a', '2026-06-03 15:30:00'),
 ('P-0007', 'Ravi',    'Menon',   'ravi.menon@email.com',   NULL,         77.1, '01', 'Y',  '4',   '2026-06-04 11:10:00'),
 ('P-0008', 'Anna',    'Petrov',  'anna.petrov@email.com',  '1990-12-25', 59.3, '02', 'Y',  '9',   '2026-06-04 16:45:00'),
 ('P-0009', 'Tom',     'Nguyen',  'TOM.N@EMAIL.COM',        '1987-04-11', NULL, '03', 'Y',  NULL,  '2026-06-05 10:00:00'),
 ('P-0010', 'Lakshmi', 'Rao',     'lakshmi.rao@email.com',  '1993-08-19', 63.7, '01', 'N',  '2',   '2026-06-05 14:20:00'),
 ('P-0011', 'Omar',    NULL,      'omar@email.com',         '1981-02-28', 90.5, '04', 'Y',  '15',  '2026-06-06 09:30:00'),
 ('P-0012', NULL,      'Silva',   ' silva@email.com',       '2000-10-10', 48.2, NULL, 'N',  '0',   '2026-06-06 13:05:00'),
 ('P-0013', 'Chen',    'Wei',     'chen.wei@email.com',     'unknown',    66.6, '02', 'Y',  '5',   '2026-06-07 08:50:00'),
 ('P-0014', 'Fatima',  'Zahra',   'Fatima.Z@Email.com',     '1976-06-01', 72.8, '03', 'n',  '6',   '2026-06-07 17:15:00'),
 ('P-0015', 'Ken',     'Tanaka',  'ken.tanaka@email.com',   '1998-03-03', 81.0, '01', 'Y',  '11',  '2026-06-08 10:40:00');

-- The ingestion payload dominates the table's size, as it does in real raw layers.
UPDATE raw.clinical_patients SET raw_payload =
  '{"system":"edc-v2","record":"' || patient_id || '","site":"' || COALESCE(site_code, '') ||
  '","consent":{"version":"3.1","signed":true},"audit":[' ||
  repeat('{"event":"field_update","by":"coordinator","reason":"source data verification"},', 12) ||
  '{"event":"export"}]}';

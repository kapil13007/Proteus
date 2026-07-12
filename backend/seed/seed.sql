-- Demo data: one source table, one (empty) target table.
CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS analytics;

DROP TABLE IF EXISTS raw.clinical_patients;
CREATE TABLE raw.clinical_patients (
    patient_id      VARCHAR NOT NULL,
    first_name      VARCHAR,
    last_name       VARCHAR,
    cust_email_01   VARCHAR,
    dob             VARCHAR,          -- ISO-8601 string, needs parsing
    weight_kg       DOUBLE PRECISION,
    site_code       VARCHAR,          -- '01' | '02' | '03', lookup to city
    enrolled_flag   VARCHAR,          -- 'Y' / 'N'
    created_at      TIMESTAMP
);

INSERT INTO raw.clinical_patients VALUES
 ('P-0001','John','Doe','  John.DOE@Email.com ','1985-03-14',82.4,'01','Y','2026-06-01 09:15:00'),
 ('P-0002','Priya','Sharma','priya.sharma@email.com','1992-11-02',61.0,'02','Y','2026-06-01 10:20:00'),
 ('P-0003','Arun','Kumar','ARUN.K@email.com','1978-07-23',NULL,'03','N','2026-06-02 08:05:00'),
 ('P-0004','Meera','Iyer',NULL,'1989-01-30',55.6,'01','Y','2026-06-02 12:40:00'),
 ('P-0005','David','Lee','david.lee@email.com','1995-09-17',70.2,'02','Y','2026-06-03 09:00:00'),
 ('P-0006','Sara','Khan','sara.khan@Email.com','1983-05-08',68.9,'03','N','2026-06-03 15:30:00'),
 ('P-0007','Ravi','Menon','ravi.menon@email.com',NULL,77.1,'01','Y','2026-06-04 11:10:00'),
 ('P-0008','Anna','Petrov','anna.petrov@email.com','1990-12-25',59.3,'02','Y','2026-06-04 16:45:00'),
 ('P-0009','Tom','Nguyen','tom.n@email.com','1987-04-11',NULL,'03','Y','2026-06-05 10:00:00'),
 ('P-0010','Lakshmi','Rao','lakshmi.rao@email.com','1993-08-19',63.7,'01','N','2026-06-05 14:20:00');

DROP TABLE IF EXISTS analytics.fct_clinical_patients;
CREATE TABLE analytics.fct_clinical_patients (
    patient_id      VARCHAR NOT NULL,
    full_name       VARCHAR,
    email_address   VARCHAR,
    date_of_birth   DATE,
    weight          INTEGER,
    site_city       VARCHAR,
    is_enrolled     BOOLEAN,
    _loaded_at      TIMESTAMP NOT NULL
);

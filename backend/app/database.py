import uuid

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Float,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=lambda: uuid.uuid4().hex)
    email = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=True)
    name = Column(String, default="")
    created_at = Column(BigInteger, default=0)


class RunRecord(Base):
    __tablename__ = "runs"

    id = Column(String, primary_key=True)
    created_by = Column(String, nullable=True)  # creator's email
    target_table = Column(String, default="")
    status = Column(String, default="running")  # running|awaiting_review|succeeded|failed|rejected
    current_step = Column(Integer, default=0)
    step_failed = Column(Boolean, default=False)
    attempt_current = Column(Integer, nullable=True)
    attempt_max = Column(Integer, nullable=True)

    # Uploaded file contents (STTM normalized to CSV text)
    source_schema_md = Column(Text, default="")
    target_schema_md = Column(Text, default="")
    sttm_csv = Column(Text, default="")
    repo_structure_md = Column(Text, default="")
    udf_definitions_md = Column(Text, default="")
    file_names = Column(JSONB, default=list)

    # Agent outputs
    sqlx_code = Column(Text, default="")
    sqlx_path = Column(String, default="")
    feed = Column(JSONB, default=list)      # [{id, ts, kind, text}]
    findings = Column(JSONB, default=list)  # [{id, severity, rows, message}]
    mappings_validated = Column(Integer, default=0)
    mappings_excluded = Column(Integer, default=0)
    cost_gb = Column(Float, nullable=True)
    cost_usd = Column(Float, nullable=True)
    llm_attempts = Column(Integer, default=0)
    llm_prompt_tokens = Column(Integer, default=0)
    llm_completion_tokens = Column(Integer, default=0)
    llm_cost_usd = Column(Float, default=0.0)

    audit_rows_written = Column(Integer, nullable=True)
    audit_counts_match = Column(Boolean, nullable=True)
    audit_nulls_check = Column(Boolean, nullable=True)
    audit_failed_check = Column(String, nullable=True)

    approved_by = Column(String, nullable=True)
    workflow_id = Column(String, nullable=True)
    reject_feedback = Column(Text, nullable=True)

    started_at = Column(BigInteger, default=0)  # epoch ms
    duration_sec = Column(Float, nullable=True)


def create_tables() -> None:
    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

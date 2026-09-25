"""App-state database: users, runs, the append-only run event log, and the LLM cache.

SQLite by default (a file in backend/data/, no server). SQLAlchemy keeps the
DATABASE_URL swappable, so pointing it at Postgres later is a one-line change.
"""
import uuid

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    Float,
    Integer,
    String,
    Text,
    create_engine,
    event,
)
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import DATA_DIR, settings

_is_sqlite = settings.database_url.startswith("sqlite")
if _is_sqlite:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    settings.database_url,
    # The agent writes from worker threads while the API reads; SQLite allows
    # that once same-thread checking is off and WAL mode is on (below).
    connect_args={"check_same_thread": False, "timeout": 30} if _is_sqlite else {},
    pool_pre_ping=True,
)

if _is_sqlite:
    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _record):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")    # readers never block the writer
        cur.execute("PRAGMA synchronous=NORMAL")  # safe with WAL, far fewer fsyncs
        cur.execute("PRAGMA busy_timeout=5000")
        cur.close()

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
    created_by = Column(String, nullable=True)
    status = Column(String, default="running")  # running|awaiting_review|succeeded|failed|rejected
    current_step = Column(Integer, default=0)
    step_failed = Column(Boolean, default=False)
    error = Column(Text, nullable=True)
    attempt_current = Column(Integer, nullable=True)
    attempt_max = Column(Integer, nullable=True)

    # Uploaded context, stored verbatim (STTM normalised to CSV text)
    inputs = Column(JSON, default=dict)
    file_names = Column(JSON, default=list)

    # What the agent produced
    source_table = Column(String, default="")
    target_table = Column(String, default="")
    conventions = Column(JSON, default=dict)   # where files go + the evidence for it
    udf_catalog = Column(JSON, default=list)
    decisions = Column(JSON, default=list)     # one per STTM row: how it was implemented and why
    files = Column(JSON, default=list)         # [{path, kind, content, description}]
    findings = Column(JSON, default=list)      # [{id, severity, rows, message}]
    preview = Column(JSON, default=dict)       # sandbox output sample
    pipeline_sql = Column(Text, default="")    # verified SQL (local dialect) executed on approval
    metrics = Column(JSON, default=dict)       # tokens, cache hits, bytes, stage timings
    revisions = Column(JSON, default=list)     # reviewer feedback / overrides history
    mappings_validated = Column(Integer, default=0)
    mappings_excluded = Column(Integer, default=0)

    audit = Column(JSON, nullable=True)
    publish = Column(JSON, nullable=True)
    approved_by = Column(String, nullable=True)
    reject_feedback = Column(Text, nullable=True)

    started_at = Column(BigInteger, default=0)  # epoch ms
    duration_sec = Column(Float, nullable=True)


class RunEvent(Base):
    """Append-only activity log. One INSERT per event instead of rewriting a JSON blob."""
    __tablename__ = "run_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String, index=True, nullable=False)
    ts = Column(String, default="")  # HH:MM:SS, for display
    kind = Column(String, default="thought")  # thought|tool_call|tool_result|tool_error
    text = Column(Text, default="")


class LlmCacheEntry(Base):
    """Content-addressed cache of LLM translations that passed verification."""
    __tablename__ = "llm_cache"

    key = Column(String, primary_key=True)  # sha256 of everything the answer depends on
    value = Column(JSON, nullable=False)
    model = Column(String, default="")
    created_at = Column(BigInteger, default=0)
    hits = Column(Integer, default=0)


def create_tables() -> None:
    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

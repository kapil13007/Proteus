"""Runtime settings, loaded from backend/.env (environment variables win).

Every default points at a free resource that runs on your machine: SQLite for
app state, an embedded DuckDB file as the warehouse sandbox, and Groq's free
API tier for the LLM. Nothing here needs Docker, a database server or billing.
"""
import os
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BACKEND_DIR / "data"
# MAPFLOW_ENV_FILE="" disables the .env file entirely (the test suite uses this to stay hermetic).
_ENV_FILE = os.environ.get("MAPFLOW_ENV_FILE", str(BACKEND_DIR / ".env")) or None
DEV_SESSION_SECRET = "change-me-in-dev-use-a-long-random-string"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_ENV_FILE, extra="ignore")

    # App state (users, runs, event log, LLM cache). Any SQLAlchemy URL works;
    # SQLite needs no server and lives in backend/data/.
    database_url: str = f"sqlite:///{(DATA_DIR / 'mapflow.db').as_posix()}"

    # Local warehouse sandbox: an embedded DuckDB file standing in for BigQuery.
    warehouse_path: str = str(DATA_DIR / "warehouse.duckdb")
    seed_demo_data: bool = True
    # Dialect the generated Dataform code is written in (the real warehouse).
    target_dialect: str = "bigquery"
    # Source rows sampled for the sandbox dry run.
    sample_rows: int = 200

    # LLM: Groq free tier (30 req/min, 8K tokens/min for gpt-oss-120b).
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_reasoning_effort: str = "low"
    llm_timeout_sec: float = 60.0
    llm_rows_per_call: int = 20
    llm_cache: bool = True
    # Published list prices (USD / 1M tokens). On the free tier the real bill is
    # $0; these only power the "list-price equivalent" metric in the UI.
    groq_price_per_1m_input: float = 0.15
    groq_price_per_1m_cached_input: float = 0.075
    groq_price_per_1m_output: float = 0.60

    # Total LLM attempts per mapping row (1 generation + N-1 repairs).
    max_repair_attempts: int = Field(
        3, validation_alias=AliasChoices("max_repair_attempts", "max_dry_run_attempts"))

    # Optional publish step: one commit per approved run (free GitHub API).
    github_token: str = ""
    github_repo: str = ""  # e.g. kapil13007/dataform-models
    github_branch: str = "main"

    # Auth (email/password + JWT session cookie). Placeholder: set a random value in .env.
    session_secret: str = DEV_SESSION_SECRET
    cors_origins: list[str] = [
        "http://localhost:8080", "http://localhost:5173", "http://localhost:3000"]


settings = Settings()

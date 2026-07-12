from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Postgres holds both the app's run history AND the demo data
    # (schemas `raw` and `analytics`).
    database_url: str = "postgresql://mapflow:mapflow@localhost:5433/mapflow"

    # LLM
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"

    # LangSmith tracing (optional — set LANGSMITH_TRACING=true + key to enable)
    langsmith_tracing: bool = False
    langsmith_api_key: str = ""
    langsmith_project: str = "mapflow"

    # GitHub push (optional — leave GITHUB_TOKEN empty to skip the push step)
    github_token: str = ""
    github_repo: str = ""          # e.g. kapil13007/dataform-models
    github_branch: str = "main"

    # Data location inside Postgres
    source_schema: str = "raw"
    target_schema: str = "analytics"

    max_dry_run_attempts: int = 3

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()

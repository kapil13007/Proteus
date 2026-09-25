"""Health, real configuration status (never secrets), and the demo sample inputs."""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.config import BACKEND_DIR, settings
from app.database import LlmCacheEntry, User, get_db
from app.warehouse import get_warehouse

router = APIRouter()

# upload slot -> sample file (a fixed whitelist: no user-controlled paths)
SAMPLES = {"source": "source_schema.md", "target": "target_schema.md", "sttm": "sttm.xlsx",
           "repo": "folder_structure.md", "udf": "functions.js", "env": "env_vars.js"}


@router.get("/samples")
def list_samples(user: User = Depends(get_current_user)):
    return SAMPLES


@router.get("/samples/{slot}")
def get_sample(slot: str, user: User = Depends(get_current_user)):
    if slot not in SAMPLES:
        raise HTTPException(404, "no such sample")
    return FileResponse(BACKEND_DIR / "sample_inputs" / SAMPLES[slot], filename=SAMPLES[slot])


@router.get("/health")
def health():
    return {"ok": True}


@router.get("/system/status")
def system_status(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    wh = get_warehouse()
    entries, hits = db.query(func.count(LlmCacheEntry.key), func.coalesce(func.sum(LlmCacheEntry.hits), 0)).one()
    return {
        "llm": {"provider": "Groq (free tier)", "model": settings.groq_model,
                "configured": bool(settings.groq_api_key), "reasoningEffort": settings.groq_reasoning_effort,
                "rowsPerCall": settings.llm_rows_per_call, "cache": settings.llm_cache,
                "listPricePer1M": {"input": settings.groq_price_per_1m_input,
                                   "cachedInput": settings.groq_price_per_1m_cached_input,
                                   "output": settings.groq_price_per_1m_output}},
        "warehouse": {"engine": "DuckDB (embedded, local)", "path": wh.path, "tables": wh.list_tables(),
                      "targetDialect": settings.target_dialect, "sampleRows": settings.sample_rows},
        "appDb": {"engine": settings.database_url.split(":", 1)[0]},
        "github": {"configured": bool(settings.github_token and settings.github_repo),
                   "repo": settings.github_repo, "branch": settings.github_branch},
        "cache": {"entries": entries, "hits": int(hits)},
        "limits": {"maxAttempts": settings.max_repair_attempts},
    }

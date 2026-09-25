"""Process-wide warehouse handle (created lazily, seeded once, then locked down)."""
import threading

from app.config import BACKEND_DIR, settings
from app.warehouse.duckdb_wh import DuckDBWarehouse

_SEED_SQL = BACKEND_DIR / "seed" / "seed.sql"
_lock = threading.Lock()
_instance: DuckDBWarehouse | None = None


def get_warehouse() -> DuckDBWarehouse:
    global _instance
    with _lock:
        if _instance is None:
            wh = DuckDBWarehouse(settings.warehouse_path)
            if settings.seed_demo_data and "raw.clinical_patients" not in wh.list_tables():
                wh.execute_script(_SEED_SQL.read_text(encoding="utf-8"))
            wh.lock_down()
            _instance = wh
        return _instance


def reset_warehouse() -> None:
    """Close the handle (tests and shutdown)."""
    global _instance
    with _lock:
        if _instance is not None:
            _instance.close()
            _instance = None

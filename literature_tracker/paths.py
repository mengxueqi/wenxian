from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCES_CSV = PROJECT_ROOT / "文献源.csv"
CONFIG_DIR = PROJECT_ROOT / "config"
AUTHOR_WATCHLIST_CSV = CONFIG_DIR / "author_watchlist.csv"
THEME_WATCHLIST_CSV = CONFIG_DIR / "theme_watchlist.csv"
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "literature_tracker.db"
REPORTS_DIR = DATA_DIR / "reports"


def ensure_runtime_directories() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

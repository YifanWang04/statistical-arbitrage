"""IDE entry point: run this file to build the Yahoo DuckDB database."""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

from stat_arb_data.application import build_database
from stat_arb_data.config import PipelineConfig


# ---------------------------------------------------------------------------
# User-editable settings
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATABASE_PATH = PROJECT_ROOT / "data" / "yahoo_market_data.duckdb"
START_DATE = date(2020, 1, 1)
END_DATE: date | None = None  # None means the previous calendar date.
TOP_N = 500
CANDIDATE_POOL_SIZE: int | None = 1500  # None keeps all currently discoverable issuers.
PRICE_BATCH_SIZE = 100
REPLACE_EXISTING_DATABASE = True  # True explicitly replaces the existing complete database.


def main() -> None:
    """Build the configured database without requiring command-line arguments."""

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    config = PipelineConfig(
        database_path=DATABASE_PATH,
        start_date=START_DATE,
        end_date=END_DATE,
        top_n=TOP_N,
        candidate_pool_size=CANDIDATE_POOL_SIZE,
        price_batch_size=PRICE_BATCH_SIZE,
    )

    print("Starting Yahoo data download...")
    print(f"Database: {DATABASE_PATH}")
    run_id = build_database(
        config,
        replace_existing=REPLACE_EXISTING_DATABASE,
    )
    print(f"Download completed. Run id: {run_id}")
    print("Run scripts/view_data.py to browse the database.")


if __name__ == "__main__":
    main()

"""IDE entry point: run this file to browse the DuckDB database."""

from pathlib import Path

from stat_arb_data.viewer import open_database_ui


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATABASE_PATH = PROJECT_ROOT / "data" / "yahoo_market_data.duckdb"


if __name__ == "__main__":
    open_database_ui(DATABASE_PATH)

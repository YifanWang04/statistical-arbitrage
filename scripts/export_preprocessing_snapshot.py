"""IDE entry point: export one point-in-time preprocessing snapshot to Excel."""

from datetime import date
from pathlib import Path

from stat_arb_preprocessing import PreprocessingConfig, get_snapshot
from stat_arb_preprocessing.excel import export_snapshot_workbook


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATABASE_PATH = PROJECT_ROOT / "data" / "yahoo_market_data.duckdb"
AS_OF_DATE = date(2026, 7, 17)
OUTPUT_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "preprocessing"
    / f"preprocessing_snapshot_{AS_OF_DATE.isoformat()}.xlsx"
)
REPLACE_EXISTING = True


def main() -> None:
    config = PreprocessingConfig(database_path=DATABASE_PATH)
    snapshot = get_snapshot(config, AS_OF_DATE, cache=True)
    output = export_snapshot_workbook(
        snapshot,
        OUTPUT_PATH,
        replace_existing=REPLACE_EXISTING,
    )
    print(f"Excel snapshot exported: {output}")


if __name__ == "__main__":
    main()

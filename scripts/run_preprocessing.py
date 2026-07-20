"""IDE entry point: build rolling beta and market residual returns."""

from pathlib import Path

from stat_arb_preprocessing import PreprocessingConfig, build_preprocessing


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATABASE_PATH = PROJECT_ROOT / "data" / "yahoo_market_data.duckdb"


def main() -> None:
    config = PreprocessingConfig(database_path=DATABASE_PATH)
    print(f"Building preprocessing data in: {DATABASE_PATH}")
    run_id = build_preprocessing(config)
    print(f"Preprocessing completed. Run id: {run_id}")


if __name__ == "__main__":
    main()

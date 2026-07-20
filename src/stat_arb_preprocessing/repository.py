from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

from .config import PreprocessingConfig
from .models import PreprocessingRun, PreprocessingSnapshot, SnapshotQuality


EXPECTED_RETURN_BASIS = "split_consistent_close_price_return_excluding_dividends"


SCHEMA_SQL = """
CREATE SCHEMA IF NOT EXISTS preprocessing;

CREATE TABLE IF NOT EXISTS audit.preprocessing_runs (
    run_id VARCHAR PRIMARY KEY,
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    status VARCHAR NOT NULL,
    input_max_date DATE,
    beta_window INTEGER NOT NULL,
    correlation_window INTEGER NOT NULL,
    beta_alignment VARCHAR NOT NULL,
    missing_policy VARCHAR NOT NULL,
    calculation_version VARCHAR NOT NULL,
    variance_epsilon DOUBLE NOT NULL,
    return_basis VARCHAR NOT NULL,
    notes VARCHAR
);

CREATE TABLE IF NOT EXISTS preprocessing.daily_market_residuals (
    trade_date DATE NOT NULL,
    ticker VARCHAR NOT NULL,
    stock_return DOUBLE,
    market_return DOUBLE,
    beta DOUBLE,
    market_residual_return DOUBLE,
    beta_window_start DATE,
    beta_window_end DATE,
    beta_observation_count INTEGER NOT NULL,
    is_valid BOOLEAN NOT NULL,
    exclusion_reason VARCHAR,
    calculation_run_id VARCHAR NOT NULL,
    PRIMARY KEY (trade_date, ticker)
);

CREATE TABLE IF NOT EXISTS preprocessing.correlation_snapshots (
    snapshot_id VARCHAR PRIMARY KEY,
    preprocessing_run_id VARCHAR NOT NULL,
    as_of_date DATE NOT NULL UNIQUE,
    window_start DATE NOT NULL,
    window_end DATE NOT NULL,
    beta_window INTEGER NOT NULL,
    correlation_window INTEGER NOT NULL,
    beta_alignment VARCHAR NOT NULL,
    missing_policy VARCHAR NOT NULL,
    calculation_version VARCHAR NOT NULL,
    variance_epsilon DOUBLE NOT NULL,
    return_basis VARCHAR NOT NULL,
    selected_stock_count INTEGER NOT NULL,
    valid_stock_count INTEGER NOT NULL,
    excluded_stock_count INTEGER NOT NULL,
    maximum_asymmetry DOUBLE NOT NULL,
    minimum_correlation DOUBLE NOT NULL,
    maximum_correlation DOUBLE NOT NULL,
    minimum_eigenvalue DOUBLE NOT NULL,
    numerical_rank INTEGER NOT NULL,
    has_non_finite_values BOOLEAN NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS preprocessing.snapshot_residuals (
    snapshot_id VARCHAR NOT NULL,
    trade_date DATE NOT NULL,
    column_index INTEGER NOT NULL,
    ticker VARCHAR NOT NULL,
    market_cap_rank INTEGER NOT NULL,
    stock_return DOUBLE NOT NULL,
    market_return DOUBLE NOT NULL,
    beta DOUBLE NOT NULL,
    market_residual_return DOUBLE NOT NULL,
    PRIMARY KEY (snapshot_id, trade_date, column_index)
);

CREATE TABLE IF NOT EXISTS preprocessing.snapshot_correlations (
    snapshot_id VARCHAR NOT NULL,
    row_index INTEGER NOT NULL,
    column_index INTEGER NOT NULL,
    ticker_i VARCHAR NOT NULL,
    ticker_j VARCHAR NOT NULL,
    correlation DOUBLE NOT NULL,
    CHECK (row_index <= column_index),
    PRIMARY KEY (snapshot_id, row_index, column_index)
);

CREATE TABLE IF NOT EXISTS preprocessing.snapshot_exclusions (
    snapshot_id VARCHAR NOT NULL,
    ticker VARCHAR NOT NULL,
    market_cap_rank INTEGER NOT NULL,
    reason VARCHAR NOT NULL,
    PRIMARY KEY (snapshot_id, ticker)
);
"""


DATA_DICTIONARY = (
    ("preprocessing.daily_market_residuals", "beta", "包含当日的配置交易日窗口滚动 CAPM beta"),
    ("preprocessing.daily_market_residuals", "market_residual_return", "股票价格收益减 beta 乘 SPY 价格收益；不扣除 alpha"),
    ("preprocessing.daily_market_residuals", "beta_observation_count", "滚动窗口内股票和 SPY 收益同时有效的观测数"),
    ("preprocessing.correlation_snapshots", "as_of_date", "快照用于该交易日决策；矩阵仅使用此前交易日"),
    ("preprocessing.snapshot_residuals", "market_residual_return", "相关矩阵快照实际使用的配置窗口残差收益"),
    ("preprocessing.snapshot_correlations", "correlation", "配置窗口残差收益的 Pearson 相关系数；仅保存上三角"),
    ("preprocessing.snapshot_exclusions", "reason", "股票未进入指定日期相关矩阵的确定性原因"),
)


class PreprocessingRepository:
    def __init__(self, database_path: Path, *, read_only: bool = False) -> None:
        self.database_path = Path(database_path).resolve()
        if not self.database_path.exists():
            raise FileNotFoundError(f"Database does not exist: {self.database_path}")
        self._connection = duckdb.connect(str(self.database_path), read_only=read_only)

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> "PreprocessingRepository":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def initialise(self) -> None:
        self._validate_source_catalog()
        self._migrate_preprocessing_schema()
        self._connection.execute(SCHEMA_SQL)
        dictionary = pd.DataFrame(
            DATA_DICTIONARY,
            columns=("object_name", "column_name", "description_zh"),
        )
        self._insert_frame("audit.data_dictionary", dictionary, replace=True)

    def _migrate_preprocessing_schema(self) -> None:
        self._connection.execute("BEGIN TRANSACTION")
        try:
            run_columns = self._table_columns("audit", "preprocessing_runs")
            if run_columns and "variance_epsilon" not in run_columns:
                self._connection.execute(
                    """
                    ALTER TABLE audit.preprocessing_runs
                    ADD COLUMN variance_epsilon DOUBLE DEFAULT 1e-15
                    """
                )
                self._connection.execute(
                    """
                    ALTER TABLE audit.preprocessing_runs
                    ALTER COLUMN variance_epsilon SET NOT NULL
                    """
                )

            daily_columns = self._table_columns("preprocessing", "daily_market_residuals")
            if "beta_60d" in daily_columns and "beta" in daily_columns:
                raise RuntimeError(
                    "daily_market_residuals contains both beta_60d and beta; "
                    "manual schema repair is required"
                )
            if "beta_60d" in daily_columns:
                self._connection.execute(
                    """
                    ALTER TABLE preprocessing.daily_market_residuals
                    RENAME COLUMN beta_60d TO beta
                    """
                )
                self._connection.execute(
                    """
                    DELETE FROM audit.data_dictionary
                    WHERE object_name = 'preprocessing.daily_market_residuals'
                      AND column_name = 'beta_60d'
                    """
                )

            cache_tables = {
                "correlation_snapshots",
                "snapshot_residuals",
                "snapshot_correlations",
                "snapshot_exclusions",
            }
            present_cache_tables = {
                table
                for table in cache_tables
                if self._table_columns("preprocessing", table)
            }
            required_metadata_columns = {
                "snapshot_id",
                "preprocessing_run_id",
                "as_of_date",
                "window_start",
                "window_end",
                "beta_window",
                "correlation_window",
                "beta_alignment",
                "missing_policy",
                "calculation_version",
                "variance_epsilon",
                "return_basis",
            }
            metadata_columns = self._table_columns(
                "preprocessing",
                "correlation_snapshots",
            )
            residual_columns = self._table_columns(
                "preprocessing",
                "snapshot_residuals",
            )
            cache_is_current = (
                not present_cache_tables
                or (
                    present_cache_tables == cache_tables
                    and required_metadata_columns.issubset(metadata_columns)
                    and "beta" in residual_columns
                    and "beta_60d" not in residual_columns
                )
            )
            if not cache_is_current:
                self._connection.execute(
                    """
                    DROP TABLE IF EXISTS preprocessing.snapshot_correlations;
                    DROP TABLE IF EXISTS preprocessing.snapshot_residuals;
                    DROP TABLE IF EXISTS preprocessing.snapshot_exclusions;
                    DROP TABLE IF EXISTS preprocessing.correlation_snapshots;
                    """
                )
            self._connection.execute("COMMIT")
        except Exception:
            self._connection.execute("ROLLBACK")
            raise

    def _table_columns(self, schema: str, table: str) -> set[str]:
        rows = self._connection.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = ? AND table_name = ?
            """,
            [schema, table],
        ).fetchall()
        return {str(row[0]) for row in rows}

    def _validate_source_catalog(self) -> None:
        required = {
            "market_data.daily_prices",
            "market_data.market_returns",
            "market_data.universe_membership",
            "audit.settings",
            "audit.data_dictionary",
        }
        rows = self._connection.execute(
            """
            SELECT table_schema || '.' || table_name
            FROM information_schema.tables
            WHERE table_schema IN ('market_data', 'audit')
            """
        ).fetchall()
        present = {str(row[0]) for row in rows}
        missing = sorted(required - present)
        if missing:
            raise RuntimeError(f"Database is missing required source objects: {missing}")

    def _insert_frame(
        self,
        table_name: str,
        frame: pd.DataFrame,
        *,
        replace: bool = False,
    ) -> None:
        if frame.empty:
            return
        registration = "_preprocessing_incoming"
        self._connection.register(registration, frame)
        try:
            verb = "INSERT OR REPLACE" if replace else "INSERT"
            self._connection.execute(
                f"{verb} INTO {table_name} BY NAME SELECT * FROM {registration}"
            )
        finally:
            self._connection.unregister(registration)

    def return_basis(self) -> str:
        row = self._connection.execute(
            """
            SELECT setting_value
            FROM audit.settings
            WHERE setting_key = 'return_basis'
            """
        ).fetchone()
        if row is None:
            raise RuntimeError("Database has no return_basis setting")
        return str(row[0])

    def input_max_date(self) -> date | None:
        row = self._connection.execute(
            "SELECT MAX(trade_date) FROM market_data.market_returns WHERE ticker = 'SPY'"
        ).fetchone()
        return row[0] if row else None

    def start_run(self, run_id: str, config: PreprocessingConfig) -> None:
        return_basis = self.return_basis()
        if return_basis != EXPECTED_RETURN_BASIS:
            raise RuntimeError(
                f"Unsupported return basis: {return_basis}; expected {EXPECTED_RETURN_BASIS}"
            )
        self._connection.execute(
            """
            INSERT INTO audit.preprocessing_runs (
                run_id,
                started_at,
                completed_at,
                status,
                input_max_date,
                beta_window,
                correlation_window,
                beta_alignment,
                missing_policy,
                calculation_version,
                variance_epsilon,
                return_basis,
                notes
            ) VALUES (?, ?, NULL, 'running', ?, ?, ?, ?, ?, ?, ?, ?, NULL)
            """,
            [
                run_id,
                datetime.now(timezone.utc),
                self.input_max_date(),
                config.beta_window,
                config.correlation_window,
                config.beta_alignment,
                config.missing_policy,
                config.calculation_version,
                config.variance_epsilon,
                return_basis,
            ],
        )

    def complete_run(self, run_id: str) -> None:
        self._connection.execute(
            """
            UPDATE audit.preprocessing_runs
            SET status = 'completed', completed_at = ?
            WHERE run_id = ?
            """,
            [datetime.now(timezone.utc), run_id],
        )

    def fail_run(self, run_id: str, error: Exception) -> None:
        self._connection.execute(
            """
            UPDATE audit.preprocessing_runs
            SET status = 'failed', completed_at = ?, notes = ?
            WHERE run_id = ?
            """,
            [datetime.now(timezone.utc), str(error), run_id],
        )

    def rebuild_daily_residuals(self, run_id: str, config: PreprocessingConfig) -> None:
        preceding = config.beta_window - 1
        beta_window = config.beta_window
        epsilon = config.variance_epsilon
        self._connection.execute("DROP TABLE IF EXISTS _preprocessing_daily_stage")
        try:
            self._connection.execute("BEGIN TRANSACTION")
            self._connection.execute(
                f"""
                CREATE TEMP TABLE _preprocessing_daily_stage AS
                WITH selected_tickers AS (
                    SELECT DISTINCT ticker
                    FROM market_data.universe_membership
                ),
                market_calendar AS (
                    SELECT trade_date, market_return
                    FROM market_data.market_returns
                    WHERE ticker = 'SPY'
                ),
                aligned AS (
                    SELECT
                        calendar.trade_date,
                        tickers.ticker,
                        prices.price_return AS stock_return,
                        calendar.market_return
                    FROM selected_tickers AS tickers
                    CROSS JOIN market_calendar AS calendar
                    LEFT JOIN market_data.daily_prices AS prices
                        ON prices.ticker = tickers.ticker
                       AND prices.trade_date = calendar.trade_date
                ),
                windowed AS (
                    SELECT
                        *,
                        COUNT(*) OVER beta_window AS calendar_observation_count,
                        COUNT(
                            CASE
                                WHEN stock_return IS NOT NULL AND market_return IS NOT NULL THEN 1
                            END
                        ) OVER beta_window AS beta_observation_count,
                        MIN(trade_date) OVER beta_window AS beta_window_start,
                        MAX(trade_date) OVER beta_window AS beta_window_end,
                        COVAR_SAMP(stock_return, market_return) OVER beta_window AS return_covariance,
                        VAR_SAMP(market_return) OVER beta_window AS market_variance
                    FROM aligned
                    WINDOW beta_window AS (
                        PARTITION BY ticker
                        ORDER BY trade_date
                        ROWS BETWEEN {preceding} PRECEDING AND CURRENT ROW
                    )
                ),
                classified AS (
                    SELECT
                        *,
                        CASE
                            WHEN stock_return IS NULL THEN 'missing_stock_return'
                            WHEN market_return IS NULL THEN 'missing_market_return'
                            WHEN calendar_observation_count < {beta_window}
                                OR beta_observation_count < {beta_window}
                                THEN 'insufficient_beta_window'
                            WHEN market_variance IS NULL OR ABS(market_variance) <= {epsilon}
                                THEN 'zero_market_variance'
                            ELSE NULL
                        END AS exclusion_reason
                    FROM windowed
                ),
                calculated AS (
                    SELECT
                        *,
                        CASE
                            WHEN exclusion_reason IS NULL
                                THEN return_covariance / market_variance
                            ELSE NULL
                        END AS beta
                    FROM classified
                )
                SELECT
                    trade_date,
                    ticker,
                    stock_return,
                    market_return,
                    beta,
                    CASE
                        WHEN exclusion_reason IS NULL
                            THEN stock_return - beta * market_return
                        ELSE NULL
                    END AS market_residual_return,
                    beta_window_start,
                    beta_window_end,
                    CAST(beta_observation_count AS INTEGER) AS beta_observation_count,
                    exclusion_reason IS NULL AS is_valid,
                    exclusion_reason,
                    '{run_id}' AS calculation_run_id
                FROM calculated
                """
            )
            self._clear_snapshot_cache()
            self._connection.execute("DELETE FROM preprocessing.daily_market_residuals")
            self._connection.execute(
                """
                INSERT INTO preprocessing.daily_market_residuals BY NAME
                SELECT * FROM _preprocessing_daily_stage
                """
            )
            self._connection.execute("COMMIT")
        except Exception:
            self._connection.execute("ROLLBACK")
            raise
        finally:
            self._connection.execute("DROP TABLE IF EXISTS _preprocessing_daily_stage")

    def _clear_snapshot_cache(self) -> None:
        self._connection.execute("DELETE FROM preprocessing.snapshot_correlations")
        self._connection.execute("DELETE FROM preprocessing.snapshot_residuals")
        self._connection.execute("DELETE FROM preprocessing.snapshot_exclusions")
        self._connection.execute("DELETE FROM preprocessing.correlation_snapshots")

    def current_completed_run(self, config: PreprocessingConfig) -> PreprocessingRun:
        run_ids = self._connection.execute(
            """
            SELECT DISTINCT calculation_run_id
            FROM preprocessing.daily_market_residuals
            """
        ).fetchall()
        if not run_ids:
            raise RuntimeError("No preprocessing residuals exist; run preprocessing build first")
        if len(run_ids) != 1:
            raise RuntimeError(
                "Daily residuals contain multiple calculation runs; run preprocessing build again"
            )
        run_id = str(run_ids[0][0])
        row = self._connection.execute(
            """
            SELECT
                run_id,
                beta_window,
                correlation_window,
                beta_alignment,
                missing_policy,
                calculation_version,
                variance_epsilon,
                return_basis
            FROM audit.preprocessing_runs
            WHERE run_id = ? AND status = 'completed'
            """
            ,
            [run_id],
        ).fetchone()
        if row is None:
            raise RuntimeError(
                f"Residuals belong to incomplete preprocessing run {run_id}; "
                "run preprocessing build again"
            )
        current = PreprocessingRun(
            run_id=str(row[0]),
            beta_window=int(row[1]),
            correlation_window=int(row[2]),
            beta_alignment=str(row[3]),
            missing_policy=str(row[4]),
            calculation_version=str(row[5]),
            variance_epsilon=float(row[6]),
            return_basis=str(row[7]),
        )
        mismatches: list[str] = []
        for name in (
            "beta_window",
            "beta_alignment",
            "missing_policy",
            "calculation_version",
            "variance_epsilon",
        ):
            requested = getattr(config, name)
            built = getattr(current, name)
            if requested != built:
                mismatches.append(f"{name}: requested={requested!r}, built={built!r}")
        actual_return_basis = self.return_basis()
        if current.return_basis != actual_return_basis:
            mismatches.append(
                "return_basis: "
                f"current database={actual_return_basis!r}, built={current.return_basis!r}"
            )
        if mismatches:
            details = "; ".join(mismatches)
            raise RuntimeError(
                f"Snapshot configuration does not match built residuals ({details}); "
                "run preprocessing build with the requested configuration"
            )
        return current

    def snapshot_inputs(
        self,
        as_of_date: date,
        correlation_window: int,
    ) -> tuple[tuple[date, ...], pd.DataFrame, pd.DataFrame]:
        market_date = self._connection.execute(
            """
            SELECT 1
            FROM market_data.market_returns
            WHERE ticker = 'SPY' AND trade_date = ?
            """,
            [as_of_date],
        ).fetchone()
        if market_date is None:
            raise ValueError(f"as_of_date is not a SPY trading date: {as_of_date}")
        membership = self._connection.execute(
            """
            SELECT ticker, market_cap_rank
            FROM market_data.universe_membership
            WHERE eligible_date = ?
            ORDER BY market_cap_rank
            """,
            [as_of_date],
        ).fetchdf()
        if membership.empty:
            raise ValueError(f"No universe membership exists for {as_of_date}")

        dates = self._connection.execute(
            """
            SELECT trade_date
            FROM market_data.market_returns
            WHERE ticker = 'SPY' AND trade_date < ?
            ORDER BY trade_date DESC
            LIMIT ?
            """,
            [as_of_date, correlation_window],
        ).fetchall()
        window_dates = tuple(row[0] for row in reversed(dates))
        if len(window_dates) != correlation_window:
            raise ValueError(
                f"Insufficient market history for {as_of_date}: "
                f"expected {correlation_window} prior sessions, got {len(window_dates)}"
            )

        residuals = self._connection.execute(
            """
            WITH window_dates AS (
                SELECT trade_date
                FROM market_data.market_returns
                WHERE ticker = 'SPY' AND trade_date < ?
                ORDER BY trade_date DESC
                LIMIT ?
            ),
            members AS (
                SELECT ticker, market_cap_rank
                FROM market_data.universe_membership
                WHERE eligible_date = ?
            )
            SELECT
                dates.trade_date,
                members.ticker,
                members.market_cap_rank,
                daily.stock_return,
                daily.market_return,
                daily.beta,
                daily.market_residual_return,
                daily.is_valid,
                daily.exclusion_reason
            FROM window_dates AS dates
            CROSS JOIN members
            LEFT JOIN preprocessing.daily_market_residuals AS daily
                ON daily.trade_date = dates.trade_date
               AND daily.ticker = members.ticker
            ORDER BY dates.trade_date, members.market_cap_rank
            """,
            [as_of_date, correlation_window, as_of_date],
        ).fetchdf()
        return window_dates, membership, residuals

    def load_snapshot(
        self,
        as_of_date: date,
        config: PreprocessingConfig,
        current_run: PreprocessingRun,
    ) -> PreprocessingSnapshot | None:
        metadata = self._connection.execute(
            """
            SELECT *
            FROM preprocessing.correlation_snapshots
            WHERE as_of_date = ?
              AND preprocessing_run_id = ?
              AND beta_window = ?
              AND correlation_window = ?
              AND beta_alignment = ?
              AND missing_policy = ?
              AND calculation_version = ?
              AND variance_epsilon = ?
              AND return_basis = ?
            """,
            [
                as_of_date,
                current_run.run_id,
                config.beta_window,
                config.correlation_window,
                config.beta_alignment,
                config.missing_policy,
                config.calculation_version,
                config.variance_epsilon,
                current_run.return_basis,
            ],
        ).fetchdf()
        if metadata.empty:
            return None
        row = metadata.iloc[0]
        snapshot_id = str(row["snapshot_id"])
        residuals = self._connection.execute(
            """
            SELECT *
            FROM preprocessing.snapshot_residuals
            WHERE snapshot_id = ?
            ORDER BY trade_date, column_index
            """,
            [snapshot_id],
        ).fetchdf()
        correlations = self._connection.execute(
            """
            SELECT *
            FROM preprocessing.snapshot_correlations
            WHERE snapshot_id = ?
            ORDER BY row_index, column_index
            """,
            [snapshot_id],
        ).fetchdf()
        exclusions = self._connection.execute(
            """
            SELECT ticker, market_cap_rank, reason
            FROM preprocessing.snapshot_exclusions
            WHERE snapshot_id = ?
            ORDER BY market_cap_rank
            """,
            [snapshot_id],
        ).fetchdf()
        return _snapshot_from_cache(row, residuals, correlations, exclusions)

    def save_snapshot(self, snapshot: PreprocessingSnapshot) -> None:
        metadata = pd.DataFrame(
            [
                {
                    "snapshot_id": snapshot.snapshot_id,
                    "preprocessing_run_id": snapshot.preprocessing_run_id,
                    "as_of_date": snapshot.as_of_date,
                    "window_start": snapshot.window_start,
                    "window_end": snapshot.window_end,
                    "beta_window": snapshot.beta_window,
                    "correlation_window": snapshot.correlation_window,
                    "beta_alignment": snapshot.beta_alignment,
                    "missing_policy": snapshot.missing_policy,
                    "calculation_version": snapshot.calculation_version,
                    "variance_epsilon": snapshot.variance_epsilon,
                    "return_basis": snapshot.return_basis,
                    "selected_stock_count": snapshot.selected_stock_count,
                    "valid_stock_count": snapshot.valid_stock_count,
                    "excluded_stock_count": snapshot.excluded_stock_count,
                    "maximum_asymmetry": snapshot.quality.maximum_asymmetry,
                    "minimum_correlation": snapshot.quality.minimum_correlation,
                    "maximum_correlation": snapshot.quality.maximum_correlation,
                    "minimum_eigenvalue": snapshot.quality.minimum_eigenvalue,
                    "numerical_rank": snapshot.quality.numerical_rank,
                    "has_non_finite_values": snapshot.quality.has_non_finite_values,
                    "created_at": datetime.now(timezone.utc),
                }
            ]
        )
        residual_rows: list[dict[str, Any]] = []
        for trade_date in snapshot.residual_matrix.index:
            for column_index, (ticker, rank) in enumerate(
                zip(snapshot.tickers, snapshot.market_cap_ranks, strict=True)
            ):
                residual_rows.append(
                    {
                        "snapshot_id": snapshot.snapshot_id,
                        "trade_date": pd.Timestamp(trade_date).date(),
                        "column_index": column_index,
                        "ticker": ticker,
                        "market_cap_rank": rank,
                        "stock_return": float(snapshot.stock_return_matrix.loc[trade_date, ticker]),
                        "market_return": float(snapshot.market_returns.loc[trade_date]),
                        "beta": float(snapshot.beta_matrix.loc[trade_date, ticker]),
                        "market_residual_return": float(snapshot.residual_matrix.loc[trade_date, ticker]),
                    }
                )
        residual_frame = pd.DataFrame(residual_rows)

        values = snapshot.correlation_matrix.to_numpy(dtype=float)
        row_indices, column_indices = np.triu_indices(len(snapshot.tickers))
        correlation_frame = pd.DataFrame(
            {
                "snapshot_id": snapshot.snapshot_id,
                "row_index": row_indices,
                "column_index": column_indices,
                "ticker_i": [snapshot.tickers[index] for index in row_indices],
                "ticker_j": [snapshot.tickers[index] for index in column_indices],
                "correlation": values[row_indices, column_indices],
            }
        )
        exclusions = snapshot.exclusions.copy()
        if not exclusions.empty:
            exclusions.insert(0, "snapshot_id", snapshot.snapshot_id)

        try:
            self._connection.execute("BEGIN TRANSACTION")
            existing = self._connection.execute(
                """
                SELECT snapshot_id
                FROM preprocessing.correlation_snapshots
                WHERE as_of_date = ?
                """,
                [snapshot.as_of_date],
            ).fetchone()
            if existing is not None:
                existing_snapshot_id = str(existing[0])
                self._connection.execute(
                    "DELETE FROM preprocessing.snapshot_correlations WHERE snapshot_id = ?",
                    [existing_snapshot_id],
                )
                self._connection.execute(
                    "DELETE FROM preprocessing.snapshot_residuals WHERE snapshot_id = ?",
                    [existing_snapshot_id],
                )
                self._connection.execute(
                    "DELETE FROM preprocessing.snapshot_exclusions WHERE snapshot_id = ?",
                    [existing_snapshot_id],
                )
                self._connection.execute(
                    "DELETE FROM preprocessing.correlation_snapshots WHERE snapshot_id = ?",
                    [existing_snapshot_id],
                )
            self._insert_frame("preprocessing.correlation_snapshots", metadata)
            self._insert_frame("preprocessing.snapshot_residuals", residual_frame)
            self._insert_frame("preprocessing.snapshot_correlations", correlation_frame)
            self._insert_frame("preprocessing.snapshot_exclusions", exclusions)
            self._connection.execute("COMMIT")
        except Exception:
            self._connection.execute("ROLLBACK")
            raise


def _snapshot_from_cache(
    metadata: pd.Series,
    residuals: pd.DataFrame,
    correlations: pd.DataFrame,
    exclusions: pd.DataFrame,
) -> PreprocessingSnapshot:
    ordered = (
        residuals.loc[:, ["column_index", "ticker", "market_cap_rank"]]
        .drop_duplicates()
        .sort_values("column_index")
    )
    tickers = tuple(ordered["ticker"].astype(str))
    ranks = tuple(ordered["market_cap_rank"].astype(int))
    residuals = residuals.copy()
    residuals["trade_date"] = pd.to_datetime(residuals["trade_date"])

    def matrix(column: str) -> pd.DataFrame:
        return (
            residuals.pivot(index="trade_date", columns="ticker", values=column)
            .reindex(columns=tickers)
            .astype(float)
        )

    beta_matrix = matrix("beta")
    stock_return_matrix = matrix("stock_return")
    residual_matrix = matrix("market_residual_return")
    market_returns = (
        residuals.loc[:, ["trade_date", "market_return"]]
        .drop_duplicates("trade_date")
        .set_index("trade_date")["market_return"]
        .sort_index()
        .astype(float)
        .rename("SPY")
    )
    size = len(tickers)
    values = np.eye(size, dtype=float)
    for item in correlations.itertuples(index=False):
        i = int(item.row_index)
        j = int(item.column_index)
        values[i, j] = float(item.correlation)
        values[j, i] = float(item.correlation)
    correlation_matrix = pd.DataFrame(values, index=tickers, columns=tickers)
    quality = SnapshotQuality(
        maximum_asymmetry=float(metadata["maximum_asymmetry"]),
        minimum_correlation=float(metadata["minimum_correlation"]),
        maximum_correlation=float(metadata["maximum_correlation"]),
        minimum_eigenvalue=float(metadata["minimum_eigenvalue"]),
        numerical_rank=int(metadata["numerical_rank"]),
        has_non_finite_values=bool(metadata["has_non_finite_values"]),
    )
    return PreprocessingSnapshot(
        snapshot_id=str(metadata["snapshot_id"]),
        preprocessing_run_id=str(metadata["preprocessing_run_id"]),
        as_of_date=pd.Timestamp(metadata["as_of_date"]).date(),
        window_start=pd.Timestamp(metadata["window_start"]).date(),
        window_end=pd.Timestamp(metadata["window_end"]).date(),
        beta_window=int(metadata["beta_window"]),
        correlation_window=int(metadata["correlation_window"]),
        beta_alignment=str(metadata["beta_alignment"]),
        missing_policy=str(metadata["missing_policy"]),
        calculation_version=str(metadata["calculation_version"]),
        variance_epsilon=float(metadata["variance_epsilon"]),
        return_basis=str(metadata["return_basis"]),
        tickers=tickers,
        market_cap_ranks=ranks,
        beta_matrix=beta_matrix,
        stock_return_matrix=stock_return_matrix,
        market_returns=market_returns,
        residual_matrix=residual_matrix,
        correlation_matrix=correlation_matrix,
        exclusions=exclusions.reset_index(drop=True),
        selected_stock_count=int(metadata["selected_stock_count"]),
        quality=quality,
    )

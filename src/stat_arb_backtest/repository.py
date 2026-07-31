from __future__ import annotations

from bisect import bisect_left
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd

from .models import BacktestConfig, BacktestMarketData


class BacktestMarketDataRepository:
    """Read-only loader for the market calendar and close-price marks."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = Path(database_path).resolve()
        if not self.database_path.exists():
            raise FileNotFoundError(
                f"Database does not exist: {self.database_path}"
            )

    def load(
        self,
        config: BacktestConfig,
        *,
        minimum_prior_sessions: int = 1,
    ) -> BacktestMarketData:
        if (
            isinstance(minimum_prior_sessions, bool)
            or not isinstance(minimum_prior_sessions, int)
            or minimum_prior_sessions < 1
        ):
            raise ValueError("minimum_prior_sessions must be a positive integer")
        with duckdb.connect(str(self.database_path), read_only=True) as connection:
            calendar = tuple(
                row[0]
                for row in connection.execute(
                    """
                    SELECT trade_date
                    FROM market_data.market_returns
                    WHERE ticker = 'SPY'
                    ORDER BY trade_date
                    """
                ).fetchall()
            )
            if config.end_date not in calendar:
                raise ValueError(
                    f"end_date is not an SPY trading session: {config.end_date}"
                )
            start_index = bisect_left(calendar, config.start_date)
            if start_index == len(calendar):
                raise ValueError(
                    "start_date has no SPY trading session on or after it: "
                    f"{config.start_date}"
                )
            start_index = max(start_index, minimum_prior_sessions)
            if start_index >= len(calendar):
                raise ValueError(
                    "start_date has no SPY return session with at least "
                    f"{minimum_prior_sessions} prior sessions"
                )
            effective_start_date = calendar[start_index]
            end_index = calendar.index(config.end_date)
            if end_index < start_index:
                raise ValueError("end_date must not precede start_date")
            previous_session = calendar[start_index - 1]
            sessions = calendar[start_index : end_index + 1]

            stock_closes = connection.execute(
                """
                WITH backtest_tickers AS (
                    SELECT DISTINCT ticker
                    FROM market_data.universe_membership
                    WHERE eligible_date BETWEEN ? AND ?
                )
                SELECT prices.trade_date, prices.ticker, prices.close
                FROM market_data.daily_prices AS prices
                INNER JOIN backtest_tickers USING (ticker)
                WHERE prices.trade_date BETWEEN ? AND ?
                ORDER BY prices.trade_date, prices.ticker
                """,
                [
                    effective_start_date,
                    config.end_date,
                    previous_session,
                    config.end_date,
                ],
            ).fetchdf()
            spy_closes = connection.execute(
                """
                SELECT trade_date, close
                FROM market_data.market_returns
                WHERE ticker = 'SPY'
                  AND trade_date BETWEEN ? AND ?
                ORDER BY trade_date
                """,
                [previous_session, config.end_date],
            ).fetchdf()

        expected_dates = pd.Index(
            (previous_session, *sessions),
            name="trade_date",
        )
        if stock_closes.empty:
            close_matrix = pd.DataFrame(index=expected_dates)
        else:
            close_matrix = stock_closes.pivot(
                index="trade_date",
                columns="ticker",
                values="close",
            ).reindex(expected_dates)
        spy_series = (
            spy_closes.set_index("trade_date")["close"].reindex(expected_dates)
        )
        if spy_series.isna().any():
            missing = [
                value.isoformat()
                for value in spy_series.index[spy_series.isna()].tolist()
            ]
            raise ValueError(f"SPY close is missing for sessions: {missing}")
        close_matrix["SPY"] = spy_series.astype(float)
        close_matrix.columns.name = None
        return BacktestMarketData(
            previous_session=previous_session,
            sessions=tuple(sessions),
            closes=close_matrix,
        )

    def find_data_pipeline_run_id(
        self,
        preprocessing_run_id: str,
    ) -> str | None:
        """Return the completed data run visible to a preprocessing run."""
        with duckdb.connect(str(self.database_path), read_only=True) as connection:
            preprocessing_row = connection.execute(
                """
                SELECT started_at
                FROM audit.preprocessing_runs
                WHERE run_id = ?
                """,
                [preprocessing_run_id],
            ).fetchone()
            if preprocessing_row is None:
                raise ValueError(
                    "preprocessing run is missing from the audit catalog: "
                    f"{preprocessing_run_id}"
                )
            pipeline_row = connection.execute(
                """
                SELECT run_id
                FROM audit.pipeline_runs
                WHERE status = 'completed'
                  AND completed_at <= ?
                ORDER BY completed_at DESC, run_id DESC
                LIMIT 1
                """,
                [preprocessing_row[0]],
            ).fetchone()
        return None if pipeline_row is None else str(pipeline_row[0])

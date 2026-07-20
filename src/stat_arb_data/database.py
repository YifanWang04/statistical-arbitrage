from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from .config import PipelineConfig


SCHEMA_SQL = """
CREATE SCHEMA IF NOT EXISTS market_data;
CREATE SCHEMA IF NOT EXISTS audit;
CREATE SCHEMA IF NOT EXISTS browse;

CREATE TABLE IF NOT EXISTS audit.pipeline_runs (
    run_id VARCHAR PRIMARY KEY,
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    status VARCHAR NOT NULL,
    source VARCHAR NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    top_n INTEGER NOT NULL,
    candidate_method VARCHAR NOT NULL,
    notes VARCHAR
);

CREATE TABLE IF NOT EXISTS audit.settings (
    setting_key VARCHAR PRIMARY KEY,
    setting_value VARCHAR,
    description_zh VARCHAR
);

CREATE TABLE IF NOT EXISTS audit.data_dictionary (
    object_name VARCHAR NOT NULL,
    column_name VARCHAR NOT NULL,
    description_zh VARCHAR NOT NULL,
    PRIMARY KEY (object_name, column_name)
);

CREATE TABLE IF NOT EXISTS market_data.security_master (
    ticker VARCHAR PRIMARY KEY,
    short_name VARCHAR,
    long_name VARCHAR,
    issuer_key VARCHAR NOT NULL,
    primary_ticker_override VARCHAR,
    exchange VARCHAR NOT NULL,
    quote_type VARCHAR NOT NULL,
    currency VARCHAR,
    current_market_cap DOUBLE,
    candidate_pool_rank INTEGER NOT NULL,
    discovered_at TIMESTAMPTZ NOT NULL,
    is_common_stock_proxy BOOLEAN NOT NULL,
    ff12_code SMALLINT,
    source VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS market_data.daily_prices (
    ticker VARCHAR NOT NULL,
    trade_date DATE NOT NULL,
    open DOUBLE,
    high DOUBLE,
    low DOUBLE,
    close DOUBLE,
    market_cap_close DOUBLE,
    adjusted_close DOUBLE,
    volume DOUBLE,
    dividends DOUBLE,
    stock_splits DOUBLE,
    capital_gains DOUBLE,
    price_return DOUBLE,
    total_return DOUBLE,
    source VARCHAR NOT NULL,
    PRIMARY KEY (ticker, trade_date)
);

CREATE TABLE IF NOT EXISTS market_data.shares_outstanding (
    ticker VARCHAR NOT NULL,
    effective_date DATE NOT NULL,
    shares_outstanding BIGINT NOT NULL,
    source VARCHAR NOT NULL,
    PRIMARY KEY (ticker, effective_date)
);

CREATE TABLE IF NOT EXISTS market_data.market_returns (
    ticker VARCHAR NOT NULL,
    trade_date DATE NOT NULL,
    close DOUBLE,
    adjusted_close DOUBLE,
    market_return DOUBLE,
    source VARCHAR NOT NULL,
    PRIMARY KEY (ticker, trade_date)
);

CREATE TABLE IF NOT EXISTS audit.download_issues (
    run_id VARCHAR NOT NULL,
    ticker VARCHAR,
    stage VARCHAR NOT NULL,
    issue VARCHAR NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL
);
"""


DATA_DICTIONARY = (
    ("market_data.security_master", "ticker", "Yahoo 当前使用的股票代码；不是跨时期稳定证券标识"),
    ("market_data.security_master", "issuer_key", "由 Yahoo 公司名称规范化得到的发行人近似标识；不是永久公司标识"),
    ("market_data.security_master", "primary_ticker_override", "用户明确指定的主要股票类别；Alphabet 固定使用 GOOG"),
    ("market_data.security_master", "exchange", "Yahoo 交易所代码：NYSE/NYSE American/NASDAQ 相关市场"),
    ("market_data.security_master", "current_market_cap", "Yahoo Screener 发现时的当前发行人市值，仅用于可选的候选池预筛选"),
    ("market_data.security_master", "candidate_pool_rank", "按发现时当前发行人市值降序得到的候选池排名；同一发行人的股票类别共享排名"),
    ("market_data.security_master", "is_common_stock_proxy", "普通股近似标志：Yahoo EQUITY 并排除明显优先股、权证、单位和权利；不等同于 CRSP SHRCD 10/11"),
    ("market_data.security_master", "ff12_code", "Fama-French 12 行业代码；本阶段按用户要求留空"),
    ("market_data.daily_prices", "close", "Yahoo Close：历史价格已按拆股统一尺度、不含股息，用于价格收益"),
    ("market_data.daily_prices", "market_cap_close", "根据未来拆股事件从 Yahoo Close 重建的当时实际成交价，仅用于历史市值"),
    ("market_data.daily_prices", "adjusted_close", "股息和拆股调整后的收盘价，用于计算总收益"),
    ("market_data.daily_prices", "total_return", "adjusted_close 的日变化率；每支股票首个观测为空"),
    ("market_data.shares_outstanding", "effective_date", "Yahoo 历史股数观测日期；只允许向未来沿用，不向过去回填"),
    ("market_data.market_returns", "market_return", "SPY 未复权 close 的日价格变化率；不包含股息"),
    ("market_data.daily_market_cap", "market_cap", "ranking_date 当时实际价格乘以可得股数；股数会按报告日至 ranking_date 的拆股事件同步调整"),
    ("market_data.daily_market_cap", "average_dollar_volume_60", "截至当日、包含当日的 60 个市场交易日平均成交额；用于同发行人股票类别选择"),
    ("market_data.universe_membership", "ranking_date", "形成股票池所用的信息日期，即 eligible_date 的前一 SPY 交易日"),
    ("market_data.universe_membership", "eligible_date", "股票进入当日可交易股票池的日期"),
    ("market_data.universe_membership", "issuer_key", "发行人近似标识；每个交易日每个发行人最多保留一支股票"),
    ("market_data.universe_membership", "primary_selection_method", "显式主要股票覆盖，或截至 ranking_date 的 60 日平均成交额选择"),
    ("market_data.universe_membership", "market_cap_rank", "ranking_date 横截面市值降序排名，代码用于确定性打破并列"),
    ("audit.download_issues", "issue", "下载或字段缺失问题；不会用未来数据静默回填"),
)


class DuckDBDataset:
    def __init__(self, database_path: Path) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = duckdb.connect(str(self.database_path))

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> "DuckDBDataset":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def initialise(self) -> None:
        self._connection.execute(SCHEMA_SQL)
        dictionary = pd.DataFrame(
            DATA_DICTIONARY,
            columns=("object_name", "column_name", "description_zh"),
        )
        self._insert_frame("audit.data_dictionary", dictionary, replace=True)

    def _insert_frame(
        self,
        table_name: str,
        frame: pd.DataFrame,
        *,
        replace: bool = False,
        required_columns: tuple[str, ...] | None = None,
    ) -> None:
        if frame.empty:
            return
        if required_columns is not None:
            missing = sorted(set(required_columns) - set(frame.columns))
            if missing:
                raise ValueError(f"{table_name} is missing required columns: {missing}")
            frame = frame.loc[:, required_columns]
        registration = "_incoming_frame"
        self._connection.register(registration, frame)
        try:
            verb = "INSERT OR REPLACE" if replace else "INSERT"
            self._connection.execute(
                f"{verb} INTO {table_name} BY NAME SELECT * FROM {registration}"
            )
        finally:
            self._connection.unregister(registration)

    def start_run(
        self,
        run_id: str,
        started_at: datetime,
        config: PipelineConfig,
    ) -> None:
        candidate_description = (
            "全部当前可发现普通股发行人"
            if config.candidate_pool_size is None
            else f"当前市值前 {config.candidate_pool_size} 个普通股发行人"
        )
        candidate_method = (
            "all_currently_discoverable_common_issuers"
            if config.candidate_pool_size is None
            else "current_market_cap_top_issuer_pool"
        )
        self._insert_frame(
            "audit.pipeline_runs",
            pd.DataFrame(
                [
                    {
                        "run_id": run_id,
                        "started_at": started_at,
                        "completed_at": pd.NaT,
                        "status": "running",
                        "source": "yfinance",
                        "start_date": config.start_date,
                        "end_date": config.end_date,
                        "top_n": config.top_n,
                        "candidate_method": candidate_method,
                        "notes": (
                            f"{candidate_description}；每日每个发行人只保留一支普通股；"
                            "价格收益不含股息；当前 Yahoo 无法发现的历史退市股票仍会遗漏；"
                            "FF12 留空"
                        ),
                    }
                ]
            ),
        )
        self._set_settings(
            {
                "sample_start": (config.start_date, "用户确认的数据起始日"),
                "sample_end_inclusive": (config.end_date, "下载包含的最后日期；非交易日自动无记录"),
                "top_n": (config.top_n, "每日按 t-1 市值选取的股票数量上限"),
                "candidate_pool_size": (
                    config.candidate_pool_size,
                    "可选的当前发行人市值预筛选数量；空值表示保留全部当前可发现发行人",
                ),
                "selection_lag_sessions": (1, "使用前一 SPY 交易日信息形成当日股票池"),
                "candidate_method": (
                    candidate_method,
                    f"{candidate_description}；历史退市证券仍受 Yahoo 当前发现能力限制",
                ),
                "common_stock_definition": (
                    "Yahoo EQUITY minus obvious preferred/warrant/unit/right securities",
                    "Yahoo 普通股近似；排除明显优先股、权证、单位和权利，不等同 CRSP SHRCD 10/11",
                ),
                "return_basis": (
                    "split_consistent_close_price_return_excluding_dividends",
                    "股票与 SPY 策略收益均由 Yahoo Close 计算：拆股尺度一致，但不包含股息",
                ),
                "issuer_selection": (
                    "explicit override, otherwise trailing 60-session average dollar volume at t-1",
                    "每个交易日每个发行人只保留一条股票线；Alphabet 固定 GOOG，其余按 t-1 时点流动性",
                ),
                "historical_universe_limitation": (
                    "current Yahoo discovery omits securities no longer discoverable today",
                    "逐日排名使用历史行情，但 Yahoo 不能完整枚举历史退市证券，仍存在 survivorship bias",
                ),
                "ff12_status": ("NULL", "本阶段按用户要求暂不填充"),
            }
        )

    def _set_settings(self, settings: dict[str, tuple[Any, str]]) -> None:
        frame = pd.DataFrame(
            [
                {
                    "setting_key": key,
                    "setting_value": None if value is None else str(value),
                    "description_zh": description,
                }
                for key, (value, description) in settings.items()
            ]
        )
        self._insert_frame("audit.settings", frame, replace=True)

    def save_security_master(self, frame: pd.DataFrame) -> None:
        self._insert_frame(
            "market_data.security_master",
            frame,
            required_columns=(
                "ticker",
                "short_name",
                "long_name",
                "issuer_key",
                "primary_ticker_override",
                "exchange",
                "quote_type",
                "currency",
                "current_market_cap",
                "candidate_pool_rank",
                "discovered_at",
                "is_common_stock_proxy",
                "ff12_code",
                "source",
            ),
        )

    def save_daily_prices(self, frame: pd.DataFrame) -> None:
        self._insert_frame(
            "market_data.daily_prices",
            frame,
            required_columns=(
                "ticker",
                "trade_date",
                "open",
                "high",
                "low",
                "close",
                "market_cap_close",
                "adjusted_close",
                "volume",
                "dividends",
                "stock_splits",
                "capital_gains",
                "price_return",
                "total_return",
                "source",
            ),
        )

    def save_shares_outstanding(self, frame: pd.DataFrame) -> None:
        self._insert_frame(
            "market_data.shares_outstanding",
            frame,
            required_columns=("ticker", "effective_date", "shares_outstanding", "source"),
        )

    def save_market_prices(self, frame: pd.DataFrame) -> None:
        required = (
            "ticker",
            "trade_date",
            "close",
            "adjusted_close",
            "price_return",
            "total_return",
            "source",
        )
        missing = sorted(set(required) - set(frame.columns))
        if missing:
            raise ValueError(f"market prices are missing required columns: {missing}")
        market = frame.loc[:, required].drop(columns=["total_return"]).rename(
            columns={"price_return": "market_return"}
        )
        self._insert_frame(
            "market_data.market_returns",
            market,
            required_columns=(
                "ticker",
                "trade_date",
                "close",
                "adjusted_close",
                "market_return",
                "source",
            ),
        )

    def record_download_issue(
        self,
        run_id: str,
        ticker: str | None,
        stage: str,
        issue: str,
    ) -> None:
        self._insert_frame(
            "audit.download_issues",
            pd.DataFrame(
                [
                    {
                        "run_id": run_id,
                        "ticker": ticker,
                        "stage": stage,
                        "issue": issue[:4000],
                        "recorded_at": datetime.now(timezone.utc),
                    }
                ]
            ),
        )

    def complete_run(self, run_id: str) -> None:
        self._connection.execute(
            """
            UPDATE audit.pipeline_runs
            SET status = 'completed', completed_at = ?
            WHERE run_id = ?
            """,
            [datetime.now(timezone.utc), run_id],
        )
        self._connection.execute("CHECKPOINT")

    def fail_run(self, run_id: str, error: Exception) -> None:
        self._connection.execute(
            """
            UPDATE audit.pipeline_runs
            SET status = 'failed', completed_at = ?, notes = notes || ?
            WHERE run_id = ?
            """,
            [datetime.now(timezone.utc), f"; failure={error}", run_id],
        )

    def materialise_universe(self, top_n: int) -> None:
        self._connection.execute(
            """
            CREATE OR REPLACE TABLE market_data.daily_market_cap AS
            WITH priced AS (
                SELECT
                    trade_date,
                    ticker,
                    close,
                    market_cap_close,
                    volume,
                    AVG(close * volume) OVER (
                        PARTITION BY ticker
                        ORDER BY trade_date
                        ROWS BETWEEN 59 PRECEDING AND CURRENT ROW
                    ) AS average_dollar_volume_60
                FROM market_data.daily_prices
            ),
            shares_asof AS (
                SELECT
                    p.trade_date,
                    p.ticker,
                    p.close,
                    p.market_cap_close,
                    p.volume,
                    p.average_dollar_volume_60,
                    s.shares_outstanding AS reported_shares_outstanding,
                    s.effective_date AS shares_effective_date
                FROM priced AS p
                ASOF LEFT JOIN market_data.shares_outstanding AS s
                    ON p.ticker = s.ticker
                   AND p.trade_date >= s.effective_date
                INNER JOIN market_data.security_master AS sm
                    ON p.ticker = sm.ticker
                WHERE sm.is_common_stock_proxy
                  AND p.market_cap_close > 0
                  AND s.shares_outstanding > 0
            ),
            split_adjusted AS (
                SELECT
                    p.trade_date,
                    p.ticker,
                    p.market_cap_close,
                    p.volume,
                    p.average_dollar_volume_60,
                    p.reported_shares_outstanding,
                    p.shares_effective_date,
                    COALESCE(PRODUCT(actions.stock_splits), 1.0) AS split_factor
                FROM shares_asof AS p
                LEFT JOIN market_data.daily_prices AS actions
                    ON actions.ticker = p.ticker
                   AND actions.trade_date >= p.shares_effective_date
                   AND actions.trade_date <= p.trade_date
                   AND actions.stock_splits > 0
                GROUP BY
                    p.trade_date,
                    p.ticker,
                    p.market_cap_close,
                    p.volume,
                    p.average_dollar_volume_60,
                    p.reported_shares_outstanding,
                    p.shares_effective_date
            )
            SELECT
                p.trade_date,
                p.ticker,
                p.market_cap_close AS close,
                p.volume,
                p.average_dollar_volume_60,
                CAST(ROUND(
                    p.reported_shares_outstanding
                    * p.split_factor
                ) AS BIGINT) AS shares_outstanding,
                p.market_cap_close
                    * p.reported_shares_outstanding
                    * p.split_factor AS market_cap,
                p.shares_effective_date
            FROM split_adjusted AS p
            """
        )
        self._connection.execute(
            """
            CREATE OR REPLACE TABLE market_data.universe_membership AS
            WITH market_calendar AS (
                SELECT
                    trade_date AS eligible_date,
                    LAG(trade_date) OVER (ORDER BY trade_date) AS ranking_date
                FROM market_data.market_returns
                WHERE ticker = 'SPY'
            ),
            issuer_candidates AS (
                SELECT
                    calendar.eligible_date,
                    calendar.ranking_date,
                    cap.ticker,
                    master.issuer_key,
                    master.primary_ticker_override,
                    cap.market_cap,
                    cap.close AS ranking_close,
                    cap.shares_outstanding,
                    cap.shares_effective_date,
                    cap.average_dollar_volume_60,
                    ROW_NUMBER() OVER (
                        PARTITION BY calendar.eligible_date, master.issuer_key
                        ORDER BY
                            CASE
                                WHEN master.primary_ticker_override = cap.ticker THEN 0
                                WHEN master.primary_ticker_override IS NULL THEN 1
                                ELSE 2
                            END,
                            cap.average_dollar_volume_60 DESC NULLS LAST,
                            cap.market_cap DESC,
                            cap.ticker ASC
                    ) AS issuer_line_rank
                FROM market_calendar AS calendar
                INNER JOIN market_data.daily_market_cap AS cap
                    ON cap.trade_date = calendar.ranking_date
                INNER JOIN market_data.security_master AS master
                    ON cap.ticker = master.ticker
                WHERE calendar.ranking_date IS NOT NULL
            ),
            issuer_choice AS (
                SELECT
                    *,
                    CASE
                        WHEN primary_ticker_override = ticker
                            THEN 'explicit_primary_override'
                        WHEN primary_ticker_override IS NOT NULL
                            THEN 'override_unavailable_liquidity_fallback'
                        ELSE 'trailing_60_session_average_dollar_volume'
                    END AS primary_selection_method
                FROM issuer_candidates
                WHERE issuer_line_rank = 1
            ),
            ranked AS (
                SELECT
                    eligible_date,
                    ranking_date,
                    ticker,
                    issuer_key,
                    primary_selection_method,
                    market_cap,
                    ranking_close,
                    shares_outstanding,
                    shares_effective_date,
                    average_dollar_volume_60,
                    ROW_NUMBER() OVER (
                        PARTITION BY calendar.eligible_date
                        ORDER BY market_cap DESC, ticker ASC
                    ) AS market_cap_rank
                FROM issuer_choice AS calendar
            )
            SELECT *
            FROM ranked
            WHERE market_cap_rank <= ?
            """,
            [top_n],
        )
        self._create_browse_views()

    def _create_browse_views(self) -> None:
        self._connection.execute(
            """
            CREATE OR REPLACE VIEW browse.daily_universe AS
            SELECT
                membership.eligible_date,
                membership.ranking_date,
                membership.market_cap_rank,
                membership.ticker,
                membership.issuer_key,
                membership.primary_selection_method,
                master.long_name,
                master.exchange,
                master.ff12_code,
                membership.market_cap,
                membership.ranking_close,
                membership.shares_outstanding,
                membership.shares_effective_date,
                membership.average_dollar_volume_60,
                prices.open,
                prices.high,
                prices.low,
                prices.close,
                prices.market_cap_close,
                prices.adjusted_close,
                prices.volume,
                prices.price_return,
                prices.price_return AS strategy_return,
                prices.total_return
            FROM market_data.universe_membership AS membership
            LEFT JOIN market_data.security_master AS master USING (ticker)
            LEFT JOIN market_data.daily_prices AS prices
                ON membership.ticker = prices.ticker
               AND membership.eligible_date = prices.trade_date
            ORDER BY membership.eligible_date, membership.market_cap_rank;

            CREATE OR REPLACE VIEW browse.latest_universe AS
            SELECT *
            FROM browse.daily_universe
            WHERE eligible_date = (SELECT MAX(eligible_date) FROM market_data.universe_membership)
            ORDER BY market_cap_rank;

            CREATE OR REPLACE VIEW browse.daily_quality AS
            SELECT
                calendar.trade_date,
                COUNT(membership.ticker) AS selected_stock_count,
                COUNT(*) FILTER (WHERE membership.ticker IS NOT NULL AND prices.close IS NULL)
                    AS selected_missing_close_count,
                COUNT(*) FILTER (WHERE membership.ticker IS NOT NULL AND prices.total_return IS NULL)
                    AS selected_missing_return_count
            FROM market_data.market_returns AS calendar
            LEFT JOIN market_data.universe_membership AS membership
                ON calendar.trade_date = membership.eligible_date
            LEFT JOIN market_data.daily_prices AS prices
                ON membership.ticker = prices.ticker
               AND membership.eligible_date = prices.trade_date
            WHERE calendar.ticker = 'SPY'
            GROUP BY calendar.trade_date
            ORDER BY calendar.trade_date;
            """
        )

    def universe_membership(self) -> pd.DataFrame:
        return self._connection.execute(
            """
            SELECT eligible_date, ranking_date, ticker, market_cap_rank, market_cap
            FROM market_data.universe_membership
            ORDER BY eligible_date, market_cap_rank
            """
        ).fetchdf()

    def latest_universe(self) -> pd.DataFrame:
        return self._connection.execute(
            "SELECT * FROM browse.latest_universe ORDER BY market_cap_rank"
        ).fetchdf()

    def import_legacy_database(self, legacy_path: Path) -> None:
        """Copy a complete legacy five-schema database into the current catalog."""

        source = str(Path(legacy_path).resolve()).replace("'", "''")
        self._connection.execute(f"ATTACH '{source}' AS source_catalog (READ_ONLY)")
        copies = (
            ("audit.pipeline_runs", "source_catalog.meta.pipeline_runs"),
            ("market_data.security_master", "source_catalog.raw.security_master"),
            ("market_data.daily_prices", "source_catalog.raw.daily_prices"),
            ("market_data.shares_outstanding", "source_catalog.raw.shares_outstanding"),
            ("market_data.market_returns", "source_catalog.core.market_returns"),
            ("audit.download_issues", "source_catalog.quality.download_issues"),
        )
        try:
            self._connection.execute("BEGIN TRANSACTION")
            for target, legacy in copies:
                self._connection.execute(f"INSERT INTO {target} SELECT * FROM {legacy}")
            self._connection.execute(
                """
                INSERT INTO audit.settings
                SELECT * FROM source_catalog.meta.settings
                WHERE setting_key <> 'beta_window'
                """
            )
            self._connection.execute(
                """
                CREATE TABLE market_data.daily_market_cap AS
                SELECT * FROM source_catalog.core.daily_market_cap;
                CREATE TABLE market_data.universe_membership AS
                SELECT * FROM source_catalog.core.universe_membership;
                """
            )
            self._create_browse_views()

            comparisons = copies + (
                ("audit.settings", "source_catalog.meta.settings"),
                ("market_data.daily_market_cap", "source_catalog.core.daily_market_cap"),
                ("market_data.universe_membership", "source_catalog.core.universe_membership"),
            )
            for target, legacy in comparisons:
                current_count = self._connection.execute(
                    f"SELECT COUNT(*) FROM {target}"
                ).fetchone()[0]
                legacy_count = self._connection.execute(
                    f"SELECT COUNT(*) FROM {legacy}"
                ).fetchone()[0]
                if target == "audit.settings":
                    legacy_count = self._connection.execute(
                        """
                        SELECT COUNT(*) FROM source_catalog.meta.settings
                        WHERE setting_key <> 'beta_window'
                        """
                    ).fetchone()[0]
                if current_count != legacy_count:
                    raise RuntimeError(
                        f"Catalog upgrade count mismatch for {target}: "
                        f"expected {legacy_count}, copied {current_count}"
                    )
            self._connection.execute("COMMIT")
        except Exception:
            self._connection.execute("ROLLBACK")
            raise
        finally:
            self._connection.execute("DETACH source_catalog")
        self._connection.execute("CHECKPOINT")


class DuckDBInspector:
    """Read-only inspection interface for both current and legacy data catalogs."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = Path(database_path).resolve()
        if not self.database_path.exists():
            raise FileNotFoundError(f"Database does not exist: {self.database_path}")
        self._connection = duckdb.connect(str(self.database_path), read_only=True)
        self._schemas = {
            row[0]
            for row in self._connection.execute(
                "SELECT schema_name FROM information_schema.schemata"
            ).fetchall()
        }
        self._uses_current_catalog = {"market_data", "audit"}.issubset(self._schemas)

    @property
    def catalog_version(self) -> str:
        if self._uses_current_catalog:
            return "current"
        if {"meta", "raw", "core", "quality"}.issubset(self._schemas):
            return "legacy"
        return "unknown"

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> "DuckDBInspector":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def table_counts(self) -> list[tuple[str, int]]:
        if self._uses_current_catalog:
            objects = [
                "market_data.security_master",
                "market_data.daily_prices",
                "market_data.shares_outstanding",
                "market_data.market_returns",
                "market_data.daily_market_cap",
                "market_data.universe_membership",
                "audit.download_issues",
            ]
            if "preprocessing" in self._schemas:
                objects.extend(
                    [
                        "preprocessing.daily_market_residuals",
                        "preprocessing.correlation_snapshots",
                        "preprocessing.snapshot_residuals",
                        "preprocessing.snapshot_correlations",
                        "preprocessing.snapshot_exclusions",
                    ]
                )
        else:
            objects = [
                "raw.security_master",
                "raw.daily_prices",
                "raw.shares_outstanding",
                "core.market_returns",
                "core.daily_market_cap",
                "core.universe_membership",
                "quality.download_issues",
            ]

        results: list[tuple[str, int]] = []
        for object_name in objects:
            try:
                count = self._connection.execute(
                    f"SELECT COUNT(*) FROM {object_name}"
                ).fetchone()[0]
            except duckdb.CatalogException:
                count = 0
            results.append((object_name, int(count)))
        return results

    def recent_download_issues(self, limit: int = 20) -> pd.DataFrame:
        if limit <= 0:
            raise ValueError("limit must be positive")
        table = (
            "audit.download_issues"
            if self._uses_current_catalog
            else "quality.download_issues"
        )
        try:
            return self._connection.execute(
                f"""
                SELECT ticker, stage, issue, recorded_at
                FROM {table}
                ORDER BY recorded_at DESC
                LIMIT ?
                """,
                [limit],
            ).fetchdf()
        except duckdb.CatalogException:
            return pd.DataFrame(columns=("ticker", "stage", "issue", "recorded_at"))

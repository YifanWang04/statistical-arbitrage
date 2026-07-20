from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from .config import PipelineConfig
from .database import DuckDBDataset
from .yahoo import YahooFinanceDataSource


LOGGER = logging.getLogger(__name__)


class DataPipeline:
    def __init__(
        self,
        config: PipelineConfig,
        source: YahooFinanceDataSource | None = None,
    ) -> None:
        self.config = config
        self.source = source or YahooFinanceDataSource()

    def run(self) -> str:
        run_id = str(uuid.uuid4())
        started_at = datetime.now(timezone.utc)

        with DuckDBDataset(self.config.database_path) as dataset:
            dataset.initialise()
            dataset.start_run(run_id, started_at, self.config)

            try:
                securities = self.source.discover_current_common_stock_proxies(
                    self.config.exchanges,
                    self.config.candidate_pool_size,
                )
                if securities.empty:
                    raise RuntimeError("Yahoo screener returned no eligible equity candidates")
                dataset.save_security_master(securities)
                tickers = securities["ticker"].astype(str).tolist()
                issuer_count = securities["issuer_key"].nunique()
                LOGGER.info(
                    "Discovered %s current common-stock lines across %s issuers",
                    len(tickers),
                    issuer_count,
                )

                market_prices = self.source.download_prices(
                    ["SPY"], self.config.start_date, self.config.end_date
                )
                if market_prices.empty:
                    raise RuntimeError("SPY download returned no data")
                dataset.save_market_prices(market_prices)

                for start in range(0, len(tickers), self.config.price_batch_size):
                    batch = tickers[start : start + self.config.price_batch_size]
                    try:
                        prices = self.source.download_prices(
                            batch, self.config.start_date, self.config.end_date
                        )
                        dataset.save_daily_prices(prices)
                        downloaded = set(prices["ticker"].unique()) if not prices.empty else set()
                        for missing in sorted(set(batch) - downloaded):
                            dataset.record_download_issue(
                                run_id, missing, "prices", "No price rows returned"
                            )
                    except Exception as exc:  # continue so one provider failure is auditable
                        for ticker in batch:
                            dataset.record_download_issue(run_id, ticker, "prices", str(exc))
                    LOGGER.info("Price batches: %s/%s candidates processed", min(start + len(batch), len(tickers)), len(tickers))

                for index, ticker in enumerate(tickers, start=1):
                    try:
                        shares = self.source.download_shares(
                            ticker, self.config.start_date, self.config.end_date
                        )
                        if shares.empty:
                            dataset.record_download_issue(
                                run_id,
                                ticker,
                                "shares",
                                "No historical shares returned; excluded until an observation exists",
                            )
                        else:
                            dataset.save_shares_outstanding(shares)
                    except Exception as exc:
                        dataset.record_download_issue(run_id, ticker, "shares", str(exc))
                    if index % 50 == 0 or index == len(tickers):
                        LOGGER.info("Historical shares: %s/%s candidates processed", index, len(tickers))

                dataset.materialise_universe(self.config.top_n)
                dataset.complete_run(run_id)
            except Exception as exc:
                dataset.fail_run(run_id, exc)
                raise

        return run_id

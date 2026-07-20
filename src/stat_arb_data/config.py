from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path


YAHOO_US_EXCHANGES = ("ASE", "NCM", "NGM", "NMS", "NYQ")


def default_end_date(today: date | None = None) -> date:
    """Return a conservative inclusive end date that avoids an unfinished US session."""

    return (today or date.today()) - timedelta(days=1)


@dataclass(frozen=True)
class PipelineConfig:
    database_path: Path
    start_date: date = date(2020, 1, 1)
    end_date: date | None = None
    top_n: int = 500
    candidate_pool_size: int | None = None
    price_batch_size: int = 100
    exchanges: tuple[str, ...] = YAHOO_US_EXCHANGES

    def __post_init__(self) -> None:
        resolved_end = self.end_date or default_end_date()
        object.__setattr__(self, "end_date", resolved_end)
        object.__setattr__(self, "database_path", Path(self.database_path))

        if self.start_date >= resolved_end:
            raise ValueError("start_date must be earlier than end_date")
        if self.top_n <= 0:
            raise ValueError("top_n must be positive")
        if (
            self.candidate_pool_size is not None
            and self.candidate_pool_size < self.top_n
        ):
            raise ValueError("candidate_pool_size must be greater than or equal to top_n")
        if self.price_batch_size <= 0:
            raise ValueError("price_batch_size must be positive")
        if not self.exchanges:
            raise ValueError("at least one Yahoo exchange code is required")

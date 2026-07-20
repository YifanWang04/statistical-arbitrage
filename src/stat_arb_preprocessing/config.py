from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


DEFAULT_DATABASE = Path("data/yahoo_market_data.duckdb")


@dataclass(frozen=True)
class PreprocessingConfig:
    database_path: Path = DEFAULT_DATABASE
    beta_window: int = 60
    correlation_window: int = 5
    beta_alignment: str = "include_current_session"
    missing_policy: str = "complete_window"
    calculation_version: str = "paper_baseline_v1"
    variance_epsilon: float = 1e-15

    def __post_init__(self) -> None:
        object.__setattr__(self, "database_path", Path(self.database_path))
        if self.beta_window < 2:
            raise ValueError("beta_window must be at least 2")
        if self.correlation_window < 2:
            raise ValueError("correlation_window must be at least 2")
        if self.beta_alignment != "include_current_session":
            raise ValueError("only include_current_session beta alignment is supported")
        if self.missing_policy != "complete_window":
            raise ValueError("only complete_window missing policy is supported")
        if not self.calculation_version.strip():
            raise ValueError("calculation_version must not be empty")
        if self.variance_epsilon <= 0:
            raise ValueError("variance_epsilon must be positive")

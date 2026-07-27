"""Previous-winner/loser identification for the paper replication."""

from .application import (
    export_stock_selection_report,
    identify_stocks_for_date,
)
from .calculations import CALCULATION_VERSION, identify_stocks_to_trade
from .models import (
    NEUTRAL,
    PREVIOUS_LOSER,
    PREVIOUS_WINNER,
    StockSelectionConfig,
    StockSelectionQuality,
    StockSelectionResult,
)

__all__ = [
    "CALCULATION_VERSION",
    "NEUTRAL",
    "PREVIOUS_LOSER",
    "PREVIOUS_WINNER",
    "StockSelectionConfig",
    "StockSelectionQuality",
    "StockSelectionResult",
    "export_stock_selection_report",
    "identify_stocks_for_date",
    "identify_stocks_to_trade",
]

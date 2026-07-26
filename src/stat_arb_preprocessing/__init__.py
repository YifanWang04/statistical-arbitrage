"""Market-residual preprocessing for the statistical-arbitrage replication."""

from .application import build_preprocessing, get_snapshot
from .config import DEFAULT_CLUSTERING_CORRELATION_WINDOW, PreprocessingConfig
from .models import PreprocessingSnapshot

__all__ = [
    "PreprocessingConfig",
    "PreprocessingSnapshot",
    "DEFAULT_CLUSTERING_CORRELATION_WINDOW",
    "build_preprocessing",
    "get_snapshot",
]

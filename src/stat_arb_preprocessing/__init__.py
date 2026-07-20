"""Market-residual preprocessing for the statistical-arbitrage replication."""

from .application import build_preprocessing, get_snapshot
from .config import PreprocessingConfig
from .models import PreprocessingSnapshot

__all__ = [
    "PreprocessingConfig",
    "PreprocessingSnapshot",
    "build_preprocessing",
    "get_snapshot",
]

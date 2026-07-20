from __future__ import annotations

import os
import uuid
from dataclasses import replace
from pathlib import Path

from .config import PipelineConfig
from .database import DuckDBDataset, DuckDBInspector
from .pipeline import DataPipeline


def build_database(config: PipelineConfig, *, replace_existing: bool = False) -> str:
    """Build a complete database and publish it without exposing partial results."""

    target = config.database_path.resolve()
    target_wal = Path(f"{target}.wal")

    if target.exists() and not replace_existing:
        raise FileExistsError(
            f"Database already exists: {target}. "
            "Explicit replacement permission is required."
        )
    if target_wal.exists():
        raise RuntimeError(
            f"Database WAL exists: {target_wal}. "
            "Close DuckDB and recover or checkpoint the existing database before rebuilding."
        )

    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f"{target.name}.{uuid.uuid4().hex}.tmp")
    temporary_wal = Path(f"{temporary}.wal")
    temporary_config = replace(config, database_path=temporary)

    try:
        run_id = DataPipeline(temporary_config).run()
        os.replace(temporary, target)
        return run_id
    finally:
        temporary.unlink(missing_ok=True)
        temporary_wal.unlink(missing_ok=True)


def upgrade_database_catalog(database_path: Path) -> bool:
    """Upgrade a legacy five-schema database without downloading data again."""

    target = Path(database_path).resolve()
    target_wal = Path(f"{target}.wal")
    if target_wal.exists():
        raise RuntimeError(
            f"Database WAL exists: {target_wal}. "
            "Close DuckDB and recover or checkpoint the database before upgrading."
        )

    with DuckDBInspector(target) as inspector:
        catalog_version = inspector.catalog_version
    if catalog_version == "current":
        return False
    if catalog_version != "legacy":
        raise RuntimeError(f"Unsupported database catalog: {target}")

    temporary = target.with_name(f"{target.name}.{uuid.uuid4().hex}.catalog.tmp")
    temporary_wal = Path(f"{temporary}.wal")
    try:
        with DuckDBDataset(temporary) as dataset:
            dataset.initialise()
            dataset.import_legacy_database(target)
        os.replace(temporary, target)
        return True
    finally:
        temporary.unlink(missing_ok=True)
        temporary_wal.unlink(missing_ok=True)

from __future__ import annotations

from datetime import date
import uuid

from .calculations import build_snapshot_from_frames
from .config import PreprocessingConfig
from .models import PreprocessingSnapshot
from .repository import PreprocessingRepository


def build_preprocessing(config: PreprocessingConfig) -> str:
    run_id = str(uuid.uuid4())
    started = False
    with PreprocessingRepository(config.database_path) as repository:
        repository.initialise()
        try:
            repository.start_run(run_id, config)
            started = True
            repository.rebuild_daily_residuals(run_id, config)
            repository.complete_run(run_id)
        except Exception as exc:
            if started:
                repository.fail_run(run_id, exc)
            raise
    return run_id


def get_snapshot(
    config: PreprocessingConfig,
    as_of_date: date,
    *,
    cache: bool = True,
    read_only: bool = False,
) -> PreprocessingSnapshot:
    if read_only and cache:
        raise ValueError("read_only snapshots cannot be persisted to the cache")
    with PreprocessingRepository(
        config.database_path,
        read_only=read_only,
    ) as repository:
        if not read_only:
            repository.initialise()
        current_run = repository.current_completed_run(config)
        if cache:
            cached = repository.load_snapshot(as_of_date, config, current_run)
            if cached is not None:
                return cached
        window_dates, membership, daily_residuals = repository.snapshot_inputs(
            as_of_date,
            config.correlation_window,
        )
        snapshot = build_snapshot_from_frames(
            preprocessing_run_id=current_run.run_id,
            return_basis=current_run.return_basis,
            as_of_date=as_of_date,
            window_dates=window_dates,
            membership=membership,
            daily_residuals=daily_residuals,
            config=config,
        )
        if cache:
            repository.save_snapshot(snapshot)
        return snapshot

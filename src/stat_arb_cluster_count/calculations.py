from __future__ import annotations

import math

import numpy as np

from stat_arb_preprocessing import PreprocessingSnapshot

from .models import ClusterCountQuality, ClusterCountResult


DEFAULT_VARIANCE_THRESHOLD = 0.90
DEFAULT_CLUSTER_COUNT_ESTIMATION_WINDOW = 20
CALCULATION_VERSION = "cumulative_variance_from_preprocessing_correlation_v1"
MATRIX_TOLERANCE = 1e-12
NEGATIVE_EIGENVALUE_TOLERANCE = 1e-10
TRACE_TOLERANCE = 1e-8


def calculate_cluster_count(
    snapshot: PreprocessingSnapshot,
    variance_threshold: float = DEFAULT_VARIANCE_THRESHOLD,
) -> ClusterCountResult:
    threshold = _validate_variance_threshold(variance_threshold)
    tickers = tuple(map(str, snapshot.tickers))
    matrix = snapshot.correlation_matrix
    expected_shape = (len(tickers), len(tickers))

    if not tickers:
        raise ValueError("correlation matrix must contain at least one stock")
    if matrix.shape != expected_shape:
        raise ValueError(
            f"correlation matrix shape {matrix.shape} does not match {expected_shape}"
        )
    if tuple(map(str, matrix.index)) != tickers:
        raise ValueError("correlation matrix row labels do not match snapshot tickers")
    if tuple(map(str, matrix.columns)) != tickers:
        raise ValueError("correlation matrix column labels do not match snapshot tickers")

    values = matrix.to_numpy(dtype=float, copy=True)
    if not bool(np.isfinite(values).all()):
        raise ValueError("correlation matrix contains non-finite values")

    maximum_asymmetry = float(np.max(np.abs(values - values.T)))
    if maximum_asymmetry > MATRIX_TOLERANCE:
        raise ValueError(
            "correlation matrix is not symmetric within tolerance: "
            f"{maximum_asymmetry}"
        )
    if not np.allclose(np.diag(values), 1.0, atol=MATRIX_TOLERANCE, rtol=0.0):
        raise ValueError("correlation matrix diagonal is not one")

    symmetric_values = (values + values.T) / 2.0
    raw_eigenvalues_array = np.linalg.eigvalsh(symmetric_values)[::-1]
    minimum_raw_eigenvalue = float(raw_eigenvalues_array[-1])
    if minimum_raw_eigenvalue < -NEGATIVE_EIGENVALUE_TOLERANCE:
        raise ValueError(
            "correlation matrix is not positive semidefinite within tolerance: "
            f"minimum eigenvalue {minimum_raw_eigenvalue}"
        )

    effective_eigenvalues_array = np.where(
        raw_eigenvalues_array < 0.0,
        0.0,
        raw_eigenvalues_array,
    )
    total_variance = float(np.sum(effective_eigenvalues_array))
    if not math.isfinite(total_variance) or total_variance <= 0.0:
        raise ValueError("total variance must be finite and positive")

    trace = float(np.trace(symmetric_values))
    raw_eigenvalue_sum = float(np.sum(raw_eigenvalues_array))
    trace_difference = raw_eigenvalue_sum - trace
    if not math.isclose(
        raw_eigenvalue_sum,
        trace,
        rel_tol=1e-12,
        abs_tol=TRACE_TOLERANCE,
    ):
        raise ValueError(
            "eigenvalue sum does not reconcile to correlation-matrix trace: "
            f"difference {trace_difference}"
        )

    cumulative_variance_array = np.cumsum(effective_eigenvalues_array)
    cumulative_explained_ratio_array = cumulative_variance_array / total_variance
    cumulative_explained_ratio_array[-1] = 1.0
    qualifying = np.flatnonzero(cumulative_explained_ratio_array >= threshold)
    if qualifying.size == 0:
        raise RuntimeError("no cluster count reaches the variance threshold")
    selected_k = int(qualifying[0]) + 1

    quality = ClusterCountQuality(
        maximum_asymmetry=maximum_asymmetry,
        trace=trace,
        raw_eigenvalue_sum=raw_eigenvalue_sum,
        trace_difference=trace_difference,
        minimum_raw_eigenvalue=minimum_raw_eigenvalue,
        adjusted_negative_eigenvalue_count=int(
            np.count_nonzero(raw_eigenvalues_array < 0.0)
        ),
        numerical_rank=int(
            np.count_nonzero(
                effective_eigenvalues_array > NEGATIVE_EIGENVALUE_TOLERANCE
            )
        ),
    )
    return ClusterCountResult(
        as_of_date=snapshot.as_of_date,
        window_start=snapshot.window_start,
        window_end=snapshot.window_end,
        snapshot_id=snapshot.snapshot_id,
        preprocessing_run_id=snapshot.preprocessing_run_id,
        beta_window=snapshot.beta_window,
        cluster_count_estimation_window=snapshot.correlation_window,
        return_basis=snapshot.return_basis,
        source_calculation_version=snapshot.calculation_version,
        calculation_version=CALCULATION_VERSION,
        tickers=tickers,
        variance_threshold=threshold,
        raw_eigenvalues=tuple(map(float, raw_eigenvalues_array)),
        effective_eigenvalues=tuple(map(float, effective_eigenvalues_array)),
        cumulative_variance=tuple(map(float, cumulative_variance_array)),
        cumulative_explained_ratio=tuple(
            map(float, cumulative_explained_ratio_array)
        ),
        total_variance=total_variance,
        selected_k=selected_k,
        quality=quality,
    )


def _validate_variance_threshold(value: float) -> float:
    try:
        threshold = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("variance_threshold must be a number in (0, 1]") from exc
    if not math.isfinite(threshold) or not 0.0 < threshold <= 1.0:
        raise ValueError("variance_threshold must be a finite number in (0, 1]")
    return threshold


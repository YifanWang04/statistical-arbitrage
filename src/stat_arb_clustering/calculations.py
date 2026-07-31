from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
from scipy import linalg
from scipy.sparse.linalg import lobpcg
from sklearn.cluster import KMeans
from sklearn.exceptions import ConvergenceWarning

from stat_arb_preprocessing import PreprocessingSnapshot

from .models import (
    SIGNET_COMPAT_EMBEDDING,
    SpongeSymConfig,
    SpongeSymQuality,
    SpongeSymResult,
)


CALCULATION_VERSION = "sponge_sym_paper_text_v1"
SIGNET_COMPAT_CALCULATION_VERSION = "sponge_sym_signet_compat_v1"
CORRELATION_TOLERANCE = 1e-12
EIGENVALUE_EPSILON = 1e-12
LOBPCG_TOLERANCE = 1e-5
SIGNET_ZERO_DEGREE_FLOOR = 1.0 / 999_999_999.0


def cluster_sponge_sym(
    snapshot: PreprocessingSnapshot,
    k: int,
    config: SpongeSymConfig | None = None,
) -> SpongeSymResult:
    sponge_config = config or SpongeSymConfig()
    tickers, ranks, input_values = _validate_inputs(snapshot, k)
    size = len(tickers)

    maximum_input_asymmetry = float(
        np.max(np.abs(input_values - input_values.T))
    )
    adjacency = (input_values + input_values.T) / 2.0
    np.fill_diagonal(adjacency, 0.0)
    positive_adjacency = np.maximum(adjacency, 0.0)
    negative_adjacency = np.maximum(-adjacency, 0.0)
    reconstruction_error = float(
        np.max(
            np.abs(
                adjacency - (positive_adjacency - negative_adjacency)
            )
        )
    )

    positive_degrees = positive_adjacency.sum(axis=1)
    negative_degrees = negative_adjacency.sum(axis=1)
    positive_laplacian = _signet_symmetric_laplacian(
        positive_adjacency,
        positive_degrees,
    )
    negative_laplacian = _signet_symmetric_laplacian(
        negative_adjacency,
        negative_degrees,
    )

    signet_compat = sponge_config.embedding_mode == SIGNET_COMPAT_EMBEDDING
    calculation_version = (
        SIGNET_COMPAT_CALCULATION_VERSION
        if signet_compat
        else CALCULATION_VERSION
    )
    if signet_compat and k == 1:
        labels = np.zeros(size, dtype=int)
        eigenvalues = np.empty(0, dtype=float)
        embedding_weights = np.empty(0, dtype=float)
        residuals = np.empty(0, dtype=float)
        embedding_values = np.empty((size, 0), dtype=float)
        inertia = 0.0
        kmeans_iterations = 0
    else:
        identity = np.eye(size, dtype=float)
        numerator = (
            positive_laplacian + sponge_config.tau_negative * identity
        )
        denominator = (
            negative_laplacian + sponge_config.tau_positive * identity
        )
        random_state = np.random.RandomState(sponge_config.random_seed)
        eigenvalues, eigenvectors = _smallest_generalized_eigenpairs(
            numerator,
            denominator,
            k - 1 if signet_compat else k,
            random_state,
        )
        if not bool(np.isfinite(eigenvalues).all()):
            raise RuntimeError("generalized eigenvalues contain non-finite values")

        residuals = _generalized_eigen_residuals(
            numerator,
            denominator,
            eigenvalues,
            eigenvectors,
        )
        if signet_compat:
            if bool(np.any(eigenvalues <= EIGENVALUE_EPSILON)):
                smallest = float(np.min(eigenvalues))
                raise RuntimeError(
                    "generalized eigenvalue cannot be safely inverted: "
                    f"minimum value {smallest}"
                )
            embedding_weights = 1.0 / eigenvalues
            embedding_values = (
                eigenvectors * embedding_weights[np.newaxis, :]
            )
        else:
            embedding_weights = np.ones_like(eigenvalues)
            embedding_values = eigenvectors.copy()
        if not bool(np.isfinite(embedding_values).all()):
            raise RuntimeError("spectral embedding contains non-finite values")

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", ConvergenceWarning)
            kmeans = KMeans(
                n_clusters=k,
                init="k-means++",
                n_init=sponge_config.kmeans_n_init,
                max_iter=sponge_config.kmeans_max_iter,
                random_state=random_state,
                algorithm="lloyd",
            ).fit(embedding_values)
        convergence_messages = [
            str(item.message)
            for item in caught
            if issubclass(item.category, ConvergenceWarning)
        ]
        if convergence_messages:
            raise RuntimeError(
                "k-means++ did not produce the requested clusters: "
                + "; ".join(convergence_messages)
            )
        labels = np.asarray(kmeans.labels_, dtype=int)
        inertia = float(kmeans.inertia_)
        kmeans_iterations = int(kmeans.n_iter_)

    unique_labels = np.unique(labels)
    if unique_labels.size != k or not np.array_equal(
        unique_labels,
        np.arange(k),
    ):
        raise RuntimeError(
            f"k-means++ produced {unique_labels.size} nonempty clusters; expected {k}"
        )
    cluster_sizes_array = np.bincount(labels, minlength=k)
    embedding = pd.DataFrame(
        embedding_values,
        index=pd.Index(tickers, name="ticker"),
        columns=[
            f"component_{index}"
            for index in range(1, embedding_values.shape[1] + 1)
        ],
    )

    off_diagonal_mask = ~np.eye(size, dtype=bool)
    off_diagonal_values = input_values[off_diagonal_mask]
    quality = SpongeSymQuality(
        maximum_input_asymmetry=maximum_input_asymmetry,
        maximum_reconstruction_error=reconstruction_error,
        minimum_input_correlation=float(np.min(off_diagonal_values))
        if off_diagonal_values.size
        else 0.0,
        maximum_input_correlation=float(np.max(off_diagonal_values))
        if off_diagonal_values.size
        else 0.0,
        zero_positive_degree_count=int(np.count_nonzero(positive_degrees == 0.0)),
        zero_negative_degree_count=int(np.count_nonzero(negative_degrees == 0.0)),
        maximum_generalized_eigen_residual=float(np.max(residuals))
        if residuals.size
        else 0.0,
        kmeans_inertia=inertia,
        kmeans_iterations=kmeans_iterations,
        nonempty_cluster_count=int(unique_labels.size),
        minimum_cluster_size=int(np.min(cluster_sizes_array)),
        maximum_cluster_size=int(np.max(cluster_sizes_array)),
    )
    return SpongeSymResult(
        as_of_date=snapshot.as_of_date,
        clustering_window_start=snapshot.window_start,
        clustering_window_end=snapshot.window_end,
        clustering_snapshot_id=snapshot.snapshot_id,
        preprocessing_run_id=snapshot.preprocessing_run_id,
        beta_window=snapshot.beta_window,
        clustering_correlation_window=snapshot.correlation_window,
        return_basis=snapshot.return_basis,
        source_calculation_version=snapshot.calculation_version,
        calculation_version=calculation_version,
        requested_cluster_count=k,
        tickers=tickers,
        market_cap_ranks=ranks,
        cluster_labels=tuple(map(int, labels)),
        cluster_sizes=tuple(map(int, cluster_sizes_array)),
        generalized_eigenvalues=tuple(map(float, eigenvalues)),
        embedding_weights=tuple(map(float, embedding_weights)),
        generalized_eigen_residuals=tuple(map(float, residuals)),
        positive_degrees=tuple(map(float, positive_degrees)),
        negative_degrees=tuple(map(float, negative_degrees)),
        embedding=embedding,
        config=sponge_config,
        quality=quality,
    )


def _validate_inputs(
    snapshot: PreprocessingSnapshot,
    k: int,
) -> tuple[tuple[str, ...], tuple[int, ...], np.ndarray]:
    if isinstance(k, bool) or not isinstance(k, int):
        raise ValueError("k must be an integer between 1 and the stock count")
    tickers = tuple(map(str, snapshot.tickers))
    if not tickers:
        raise ValueError("correlation matrix must contain at least one stock")
    if len(set(tickers)) != len(tickers):
        raise ValueError("snapshot tickers must be unique")
    if not 1 <= k <= len(tickers):
        raise ValueError(
            f"k must be between 1 and the stock count {len(tickers)}"
        )
    ranks = tuple(map(int, snapshot.market_cap_ranks))
    if len(ranks) != len(tickers):
        raise ValueError("market-cap ranks do not match snapshot tickers")

    matrix = snapshot.correlation_matrix
    expected_shape = (len(tickers), len(tickers))
    if matrix.shape != expected_shape:
        raise ValueError(
            f"correlation matrix shape {matrix.shape} does not match {expected_shape}"
        )
    if tuple(map(str, matrix.index)) != tickers:
        raise ValueError("correlation matrix row labels do not match snapshot tickers")
    if tuple(map(str, matrix.columns)) != tickers:
        raise ValueError(
            "correlation matrix column labels do not match snapshot tickers"
        )
    values = matrix.to_numpy(dtype=float, copy=True)
    if not bool(np.isfinite(values).all()):
        raise ValueError("correlation matrix contains non-finite values")
    minimum = float(np.min(values))
    maximum = float(np.max(values))
    if minimum < -1.0 - CORRELATION_TOLERANCE or maximum > 1.0 + CORRELATION_TOLERANCE:
        raise ValueError(
            "correlation matrix values must lie in [-1, 1] within tolerance"
        )
    return tickers, ranks, values


def _signet_symmetric_laplacian(
    adjacency: np.ndarray,
    degrees: np.ndarray,
) -> np.ndarray:
    inverse_sqrt_degrees = 1.0 / np.maximum(
        np.sqrt(degrees),
        SIGNET_ZERO_DEGREE_FLOOR,
    )
    normalized_adjacency = (
        inverse_sqrt_degrees[:, np.newaxis]
        * adjacency
        * inverse_sqrt_degrees[np.newaxis, :]
    )
    return np.eye(adjacency.shape[0], dtype=float) - normalized_adjacency


def _smallest_generalized_eigenpairs(
    numerator: np.ndarray,
    denominator: np.ndarray,
    count: int,
    random_state: np.random.RandomState,
) -> tuple[np.ndarray, np.ndarray]:
    size = numerator.shape[0]
    if count >= size or size < 5 * count:
        eigenvalues, eigenvectors = linalg.eigh(
            numerator,
            denominator,
            subset_by_index=(0, count - 1),
            driver="gvx",
            check_finite=True,
        )
    else:
        initial = random_state.normal(0.0, 1.0, (size, count))
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            eigenvalues, eigenvectors = lobpcg(
                numerator,
                initial,
                B=denominator,
                tol=LOBPCG_TOLERANCE,
                maxiter=size,
                largest=False,
            )
        if caught:
            raise RuntimeError(
                "LOBPCG generalized eigenproblem did not converge: "
                + "; ".join(str(item.message) for item in caught)
            )

    order = np.argsort(eigenvalues)
    return (
        np.asarray(eigenvalues[order], dtype=float),
        np.asarray(eigenvectors[:, order], dtype=float),
    )


def _generalized_eigen_residuals(
    numerator: np.ndarray,
    denominator: np.ndarray,
    eigenvalues: np.ndarray,
    eigenvectors: np.ndarray,
) -> np.ndarray:
    residuals = np.empty(len(eigenvalues), dtype=float)
    for index, eigenvalue in enumerate(eigenvalues):
        vector = eigenvectors[:, index]
        residual = (
            numerator @ vector
            - float(eigenvalue) * (denominator @ vector)
        )
        residuals[index] = float(np.linalg.norm(residual))
    if not bool(np.isfinite(residuals).all()):
        raise RuntimeError("generalized eigen residuals contain non-finite values")
    return residuals

from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from .models import SpongeSymResult


HEADER_FILL = PatternFill("solid", fgColor="1F4E78")
SECTION_FILL = PatternFill("solid", fgColor="D9EAF7")
OK_FILL = PatternFill("solid", fgColor="C6EFCE")
CHECK_FILL = PatternFill("solid", fgColor="FFC7CE")
HEADER_FONT = Font(color="FFFFFF", bold=True)
FORMULA_FONT = Font(color="008000")
THIN_GRAY = Side(style="thin", color="D9E2F3")
SCIENTIFIC_FORMAT = "0.000000000000E+00"
DECIMAL_FORMAT = "0.0000000000"


def export_clustering_workbook(
    result: SpongeSymResult,
    output_path: Path,
    *,
    replace_existing: bool = False,
) -> Path:
    if result.cluster_count_result is None:
        raise ValueError(
            "clustering report requires cluster-count provenance from "
            "cluster_stocks_for_date"
        )
    output = Path(output_path).resolve()
    if output.exists() and not replace_existing:
        raise FileExistsError(
            f"Excel output already exists: {output}. Use --replace to overwrite it."
        )
    output.parent.mkdir(parents=True, exist_ok=True)

    workbook = Workbook()
    workbook.remove(workbook.active)
    parameters = workbook.create_sheet("Parameters_QC")
    eigenvalues = workbook.create_sheet("Eigenvalues")
    embedding = workbook.create_sheet("Spectral_Embedding")
    assignments = workbook.create_sheet("Cluster_Assignments")

    _write_parameters(parameters, result)
    _write_eigenvalues(eigenvalues, result)
    _write_embedding(embedding, result)
    _write_assignments(assignments, result)

    workbook.calculation.fullCalcOnLoad = True
    workbook.calculation.forceFullCalc = True
    workbook.save(output)
    return output


def _write_parameters(sheet: Worksheet, result: SpongeSymResult) -> None:
    cluster_count = result.cluster_count_result
    assert cluster_count is not None
    rows = [
        ("Parameter / QC", "Program Value", "Excel Check", "Difference / Status"),
        ("As-of date", result.as_of_date, None, None),
        (
            "Clustering window start",
            result.clustering_window_start,
            None,
            None,
        ),
        ("Clustering window end", result.clustering_window_end, None, None),
        ("Clustering snapshot id", result.clustering_snapshot_id, None, None),
        ("Cluster-count window start", cluster_count.window_start, None, None),
        ("Cluster-count window end", cluster_count.window_end, None, None),
        ("Cluster-count snapshot id", cluster_count.snapshot_id, None, None),
        ("Preprocessing run id", result.preprocessing_run_id, None, None),
        ("Return basis", result.return_basis, None, None),
        ("Beta window", result.beta_window, None, None),
        (
            "Clustering correlation window",
            result.clustering_correlation_window,
            None,
            None,
        ),
        (
            "Cluster-count estimation window",
            cluster_count.cluster_count_estimation_window,
            None,
            None,
        ),
        ("Clustering stock count N", result.stock_count, None, None),
        ("Cluster-count stock count", cluster_count.stock_count, None, None),
        ("Variance threshold P", cluster_count.variance_threshold, None, None),
        ("Selected K", result.requested_cluster_count, None, None),
        ("Embedding dimension", result.embedding_dimension, None, None),
        ("Tau positive (denominator)", result.config.tau_positive, None, None),
        ("Tau negative (numerator)", result.config.tau_negative, None, None),
        ("Random seed", result.config.random_seed, None, None),
        ("KMeans n_init", result.config.kmeans_n_init, None, None),
        ("KMeans max_iter", result.config.kmeans_max_iter, None, None),
        ("KMeans iterations used", result.quality.kmeans_iterations, None, None),
        ("KMeans inertia", result.quality.kmeans_inertia, None, None),
        (
            "Maximum generalized eigen residual",
            result.quality.maximum_generalized_eigen_residual,
            None,
            None,
        ),
        (
            "Zero positive-degree stocks",
            result.quality.zero_positive_degree_count,
            None,
            None,
        ),
        (
            "Zero negative-degree stocks",
            result.quality.zero_negative_degree_count,
            None,
            None,
        ),
        (
            "Maximum input asymmetry",
            result.quality.maximum_input_asymmetry,
            None,
            None,
        ),
        (
            "Maximum adjacency reconstruction error",
            result.quality.maximum_reconstruction_error,
            None,
            None,
        ),
        ("Source calculation version", result.source_calculation_version, None, None),
        ("Cluster-count version", cluster_count.calculation_version, None, None),
        ("Clustering version", result.calculation_version, None, None),
        (
            "Embedding convention",
            "K-1 eigenvectors scaled by inverse generalized eigenvalue",
            None,
            None,
        ),
        ("Nonempty clusters", result.quality.nonempty_cluster_count, None, None),
        ("Minimum cluster size", result.quality.minimum_cluster_size, None, None),
        ("Maximum cluster size", result.quality.maximum_cluster_size, None, None),
        ("Assignments complete", "OK", None, None),
        ("Requested clusters present", "OK", None, None),
        ("Cluster sizes reconcile", "OK", None, None),
        ("Overall QC", "OK", None, None),
    ]
    for row in rows:
        sheet.append(row)

    assignment_last_row = result.stock_count + 1
    sheet.cell(14, 3, f"=COUNTA('Cluster_Assignments'!A2:A{assignment_last_row})")
    sheet.cell(14, 4, "=C14-B14")
    sheet.cell(
        18,
        3,
        "=MAX(0,B17-1)",
    )
    sheet.cell(18, 4, "=C18-B18")
    sheet.cell(
        35,
        3,
        f'=COUNTIF(C44:C{43 + result.requested_cluster_count},">0")',
    )
    sheet.cell(35, 4, "=C35-B35")
    sheet.cell(38, 3, '=IF(C14=B14,"OK","CHECK")')
    sheet.cell(38, 4, '=IF(C38=B38,"OK","CHECK")')
    sheet.cell(39, 3, '=IF(C35=B17,"OK","CHECK")')
    sheet.cell(39, 4, '=IF(C39=B39,"OK","CHECK")')
    sheet.cell(
        40,
        3,
        f"=IF(SUM(B44:B{43 + result.requested_cluster_count})=B14,\"OK\",\"CHECK\")",
    )
    sheet.cell(40, 4, '=IF(C40=B40,"OK","CHECK")')
    sheet.cell(
        41,
        3,
        '=IF(AND(D14=0,D18=0,D35=0,D38="OK",D39="OK",D40="OK"),'
        '"OK","CHECK")',
    )
    sheet.cell(41, 4, '=IF(C41=B41,"OK","CHECK")')

    summary_header_row = 43
    sheet.cell(summary_header_row, 1, "Cluster ID")
    sheet.cell(summary_header_row, 2, "Program Size")
    sheet.cell(summary_header_row, 3, "Excel COUNTIF")
    sheet.cell(summary_header_row, 4, "Difference")
    for cluster_id, cluster_size in enumerate(result.cluster_sizes):
        row = summary_header_row + cluster_id + 1
        sheet.cell(row, 1, cluster_id)
        sheet.cell(row, 2, cluster_size)
        sheet.cell(
            row,
            3,
            (
                f'=COUNTIF(\'Cluster_Assignments\'!$C$2:$C${assignment_last_row},'
                f"A{row})"
            ),
        )
        sheet.cell(row, 4, f"=C{row}-B{row}")

    _style_header(sheet, 1, 4)
    _style_header(sheet, summary_header_row, 4)
    for row in range(2, 42):
        sheet.cell(row, 1).fill = SECTION_FILL
        sheet.cell(row, 1).font = Font(bold=True)
    for row in (2, 3, 4, 6, 7):
        sheet.cell(row, 2).number_format = "yyyy-mm-dd"
    for row in (
        11,
        12,
        13,
        14,
        15,
        17,
        18,
        21,
        22,
        23,
        24,
        27,
        28,
        35,
        36,
        37,
    ):
        for column in (2, 3, 4):
            sheet.cell(row, column).number_format = "0"
    sheet.cell(16, 2).number_format = "0.00%"
    for row in (19, 20, 25, 29, 30):
        for column in (2, 3, 4):
            sheet.cell(row, column).number_format = DECIMAL_FORMAT
    for column in (2, 3, 4):
        sheet.cell(26, column).number_format = SCIENTIFIC_FORMAT
    for row in range(2, sheet.max_row + 1):
        for column in (3, 4):
            value = sheet.cell(row, column).value
            if isinstance(value, str) and value.startswith("="):
                sheet.cell(row, column).font = FORMULA_FONT
    for row in range(summary_header_row + 1, sheet.max_row + 1):
        for column in range(1, 5):
            sheet.cell(row, column).number_format = "0"
        for column in (3, 4):
            sheet.cell(row, column).font = FORMULA_FONT

    for range_ref in ("C38:D41",):
        sheet.conditional_formatting.add(
            range_ref,
            CellIsRule(operator="equal", formula=['"OK"'], fill=OK_FILL),
        )
        sheet.conditional_formatting.add(
            range_ref,
            CellIsRule(operator="equal", formula=['"CHECK"'], fill=CHECK_FILL),
        )

    sheet.freeze_panes = f"A{summary_header_row + 1}"
    sheet.auto_filter.ref = f"A{summary_header_row}:D{sheet.max_row}"
    sheet.sheet_view.showGridLines = False
    sheet.column_dimensions["A"].width = 42
    sheet.column_dimensions["B"].width = 60
    sheet.column_dimensions["C"].width = 24
    sheet.column_dimensions["D"].width = 24


def _write_eigenvalues(sheet: Worksheet, result: SpongeSymResult) -> None:
    sheet.append(
        [
            "Rank",
            "Generalized Eigenvalue",
            "Inverse Eigenvalue Weight",
            "Final Residual Norm",
        ]
    )
    for rank, values in enumerate(
        zip(
            result.generalized_eigenvalues,
            result.inverse_eigenvalue_weights,
            result.generalized_eigen_residuals,
            strict=True,
        ),
        start=1,
    ):
        sheet.append([rank, *values])

    _style_header(sheet, 1, 4)
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = f"A1:D{max(sheet.max_row, 1)}"
    sheet.sheet_view.showGridLines = False
    sheet.column_dimensions["A"].width = 10
    for column in ("B", "C", "D"):
        sheet.column_dimensions[column].width = 28
    for row in range(2, sheet.max_row + 1):
        sheet.cell(row, 1).number_format = "0"
        for column in range(2, 5):
            sheet.cell(row, column).number_format = SCIENTIFIC_FORMAT


def _write_embedding(sheet: Worksheet, result: SpongeSymResult) -> None:
    sheet.append(["Ticker", *result.embedding.columns])
    for ticker, row in result.embedding.iterrows():
        sheet.append([ticker, *map(float, row)])

    _style_header(sheet, 1, result.embedding_dimension + 1)
    sheet.freeze_panes = "B2"
    sheet.auto_filter.ref = (
        f"A1:{get_column_letter(result.embedding_dimension + 1)}{sheet.max_row}"
    )
    sheet.sheet_view.showGridLines = False
    sheet.column_dimensions["A"].width = 16
    for column in range(2, result.embedding_dimension + 2):
        sheet.column_dimensions[get_column_letter(column)].width = 22
        for row in range(2, sheet.max_row + 1):
            sheet.cell(row, column).number_format = SCIENTIFIC_FORMAT


def _write_assignments(sheet: Worksheet, result: SpongeSymResult) -> None:
    sheet.append(
        [
            "Ticker",
            "Market Cap Rank",
            "Cluster ID (0-based)",
            "Cluster Size",
            "Positive Degree",
            "Negative Degree",
        ]
    )
    rows = zip(
        result.tickers,
        result.market_cap_ranks,
        result.cluster_labels,
        result.positive_degrees,
        result.negative_degrees,
        strict=True,
    )
    for ticker, rank, label, positive_degree, negative_degree in rows:
        sheet.append(
            [
                ticker,
                rank,
                label,
                result.cluster_sizes[label],
                positive_degree,
                negative_degree,
            ]
        )

    _style_header(sheet, 1, 6)
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = f"A1:F{sheet.max_row}"
    sheet.sheet_view.showGridLines = False
    widths = (16, 18, 22, 16, 22, 22)
    for column, width in enumerate(widths, start=1):
        sheet.column_dimensions[get_column_letter(column)].width = width
    for row in range(2, sheet.max_row + 1):
        for column in (2, 3, 4):
            sheet.cell(row, column).number_format = "0"
        for column in (5, 6):
            sheet.cell(row, column).number_format = DECIMAL_FORMAT


def _style_header(sheet: Worksheet, row: int, columns: int) -> None:
    for column in range(1, columns + 1):
        cell = sheet.cell(row, column)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = Border(bottom=THIN_GRAY)
    sheet.row_dimensions[row].height = 24

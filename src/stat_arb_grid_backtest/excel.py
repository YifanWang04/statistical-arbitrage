from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import fields
from pathlib import Path
import os
import tempfile

from openpyxl import Workbook
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from .models import GridBacktestResult, GridRunMetrics, GridRunResult


NAVY = "1F4E78"
LIGHT_BLUE = "D9EAF7"
LIGHT_GREEN = "E2F0D9"
LIGHT_RED = "FCE4D6"
LIGHT_YELLOW = "FFF2CC"
WHITE = "FFFFFF"
GREEN = "548235"
RED = "C00000"

HEADER_FILL = PatternFill("solid", fgColor=NAVY)
SECTION_FILL = PatternFill("solid", fgColor=LIGHT_BLUE)
OK_FILL = PatternFill("solid", fgColor=LIGHT_GREEN)
CHECK_FILL = PatternFill("solid", fgColor=LIGHT_RED)
BEST_FILL = PatternFill("solid", fgColor=LIGHT_YELLOW)
STRIPE_FILL = PatternFill("solid", fgColor="F8FAFC")
HEADER_FONT = Font(color=WHITE, bold=True)
THIN_GRAY = Side(style="thin", color="D9E2F3")
HEADER_BORDER = Border(bottom=THIN_GRAY)
HEADER_ALIGNMENT = Alignment(
    horizontal="center",
    vertical="center",
    wrap_text=True,
)
WRAPPED_ALIGNMENT = Alignment(vertical="top", wrap_text=True)

PERCENT_FORMAT = "0.0000%"
NAV_FORMAT = "0.000000"
RATIO_FORMAT = "0.0000"
COUNT_FORMAT = "0"
DATE_FORMAT = "yyyy-mm-dd"


def _metric(attribute: str) -> Callable[[GridRunResult], object]:
    return lambda run: (
        getattr(run.metrics, attribute) if run.metrics is not None else None
    )


RESULT_COLUMNS: tuple[
    tuple[str, Callable[[GridRunResult], object], str | None, int],
    ...,
] = (
    ("Rank", lambda run: run.rank, COUNT_FORMAT, 9),
    ("Run ID", lambda run: run.spec.run_id, None, 11),
    ("Status", lambda run: run.status, None, 12),
    ("Error Type", lambda run: run.error_type, None, 18),
    ("Error Message", lambda run: run.error_message, None, 42),
    ("w", lambda run: run.spec.lookback_window, COUNT_FORMAT, 8),
    ("p", lambda run: run.spec.deviation_threshold, PERCENT_FORMAT, 11),
    ("P", lambda run: run.spec.variance_threshold, PERCENT_FORMAT, 11),
    ("l", lambda run: run.spec.rebalance_period, COUNT_FORMAT, 8),
    ("q", lambda run: run.spec.take_profit_threshold, PERCENT_FORMAT, 11),
    ("Sessions", _metric("session_count"), COUNT_FORMAT, 12),
    ("Starting NAV", _metric("starting_nav"), NAV_FORMAT, 15),
    ("Ending NAV", _metric("ending_nav"), NAV_FORMAT, 15),
    ("Total Return", _metric("total_return"), PERCENT_FORMAT, 16),
    (
        "Annualized Return",
        _metric("annualized_return"),
        PERCENT_FORMAT,
        18,
    ),
    (
        "Mean Daily Return",
        _metric("mean_daily_return"),
        PERCENT_FORMAT,
        18,
    ),
    (
        "Annualized Volatility",
        _metric("annualized_volatility"),
        PERCENT_FORMAT,
        21,
    ),
    ("Sharpe", _metric("sharpe_ratio"), RATIO_FORMAT, 12),
    (
        "Annualized Downside Volatility",
        _metric("annualized_downside_volatility"),
        PERCENT_FORMAT,
        28,
    ),
    ("Sortino", _metric("sortino_ratio"), RATIO_FORMAT, 12),
    (
        "Maximum Drawdown",
        _metric("maximum_drawdown"),
        PERCENT_FORMAT,
        20,
    ),
    ("DD Peak Date", _metric("drawdown_peak_date"), DATE_FORMAT, 15),
    ("DD Trough Date", _metric("drawdown_trough_date"), DATE_FORMAT, 16),
    ("DD Recovery Date", _metric("drawdown_recovery_date"), DATE_FORMAT, 18),
    ("Calmar", _metric("calmar_ratio"), RATIO_FORMAT, 12),
    (
        "Positive Sessions",
        _metric("positive_session_count"),
        COUNT_FORMAT,
        18,
    ),
    (
        "Negative Sessions",
        _metric("negative_session_count"),
        COUNT_FORMAT,
        18,
    ),
    ("Zero Sessions", _metric("zero_session_count"), COUNT_FORMAT, 15),
    ("Win Rate", _metric("win_rate"), PERCENT_FORMAT, 13),
    (
        "Average Positive Return",
        _metric("average_positive_return"),
        PERCENT_FORMAT,
        23,
    ),
    (
        "Average Negative Return",
        _metric("average_negative_return"),
        PERCENT_FORMAT,
        23,
    ),
    ("Payoff Ratio", _metric("payoff_ratio"), RATIO_FORMAT, 15),
    ("Profit Factor", _metric("profit_factor"), RATIO_FORMAT, 15),
    (
        "Best Daily Return",
        _metric("best_daily_return"),
        PERCENT_FORMAT,
        18,
    ),
    (
        "Worst Daily Return",
        _metric("worst_daily_return"),
        PERCENT_FORMAT,
        19,
    ),
    ("Skewness", _metric("skewness"), RATIO_FORMAT, 13),
    (
        "Excess Kurtosis",
        _metric("excess_kurtosis"),
        RATIO_FORMAT,
        17,
    ),
    ("Daily VaR 95%", _metric("daily_var_95"), PERCENT_FORMAT, 16),
    ("Daily CVaR 95%", _metric("daily_cvar_95"), PERCENT_FORMAT, 17),
    (
        "SPY Total Return",
        _metric("spy_total_return"),
        PERCENT_FORMAT,
        18,
    ),
    (
        "SPY Annualized Return",
        _metric("spy_annualized_return"),
        PERCENT_FORMAT,
        22,
    ),
    (
        "SPY Annualized Volatility",
        _metric("spy_annualized_volatility"),
        PERCENT_FORMAT,
        24,
    ),
    ("SPY Sharpe", _metric("spy_sharpe_ratio"), RATIO_FORMAT, 14),
    ("SPY Sortino", _metric("spy_sortino_ratio"), RATIO_FORMAT, 14),
    (
        "SPY Maximum Drawdown",
        _metric("spy_maximum_drawdown"),
        PERCENT_FORMAT,
        23,
    ),
    ("SPY Calmar", _metric("spy_calmar_ratio"), RATIO_FORMAT, 14),
    (
        "Excess Total Return",
        _metric("excess_total_return"),
        PERCENT_FORMAT,
        20,
    ),
    (
        "Excess Annualized Return",
        _metric("excess_annualized_return"),
        PERCENT_FORMAT,
        24,
    ),
    ("SPY Correlation", _metric("spy_correlation"), RATIO_FORMAT, 17),
    ("SPY Beta", _metric("spy_beta"), RATIO_FORMAT, 12),
    (
        "Annualized Alpha",
        _metric("annualized_alpha"),
        PERCENT_FORMAT,
        18,
    ),
    (
        "Tracking Error",
        _metric("tracking_error"),
        PERCENT_FORMAT,
        16,
    ),
    (
        "Information Ratio",
        _metric("information_ratio"),
        RATIO_FORMAT,
        18,
    ),
    (
        "Initial Events",
        _metric("initial_event_count"),
        COUNT_FORMAT,
        15,
    ),
    (
        "Scheduled Events",
        _metric("scheduled_event_count"),
        COUNT_FORMAT,
        17,
    ),
    (
        "Stop-win Events",
        _metric("stop_win_event_count"),
        COUNT_FORMAT,
        16,
    ),
    (
        "Average Held Sessions",
        _metric("average_held_sessions"),
        "0.00",
        21,
    ),
    ("Average K", _metric("average_cluster_count"), "0.00", 13),
    (
        "Average Active Clusters",
        _metric("average_active_cluster_count"),
        "0.00",
        22,
    ),
    (
        "Average Inactive Clusters",
        _metric("average_inactive_cluster_count"),
        "0.00",
        23,
    ),
    (
        "Average Target Gross",
        _metric("average_target_gross_exposure"),
        PERCENT_FORMAT,
        21,
    ),
    (
        "Average Gross Exposure",
        _metric("average_gross_exposure"),
        PERCENT_FORMAT,
        23,
    ),
    (
        "Average Cash Weight",
        _metric("average_cash_weight"),
        PERCENT_FORMAT,
        20,
    ),
    (
        "Average Frozen Exposure",
        _metric("average_frozen_exposure"),
        PERCENT_FORMAT,
        23,
    ),
    (
        "Average Positions",
        _metric("average_position_count"),
        "0.00",
        18,
    ),
    (
        "Minimum Positions",
        _metric("minimum_position_count"),
        COUNT_FORMAT,
        18,
    ),
    (
        "Maximum Positions",
        _metric("maximum_position_count"),
        COUNT_FORMAT,
        18,
    ),
    (
        "Missing Sessions",
        _metric("missing_session_count"),
        COUNT_FORMAT,
        17,
    ),
    (
        "Missing Audit Rows",
        _metric("missing_audit_count"),
        COUNT_FORMAT,
        19,
    ),
    (
        "Annualized Two-way Turnover",
        _metric("annualized_two_way_turnover"),
        PERCENT_FORMAT,
        27,
    ),
    (
        "FIFO Status",
        _metric("fifo_reconciliation_status"),
        None,
        14,
    ),
    ("Run QC", _metric("overall_qc"), None, 12),
)


def export_grid_backtest_workbook(
    result: GridBacktestResult,
    output_path: Path,
    *,
    replace_existing: bool = False,
) -> Path:
    output = Path(output_path).resolve()
    if output.exists() and not replace_existing:
        raise FileExistsError(
            f"Excel output already exists: {output}. "
            "Use --replace to overwrite it."
        )
    output.parent.mkdir(parents=True, exist_ok=True)

    workbook = Workbook()
    workbook.remove(workbook.active)
    summary = workbook.create_sheet("Summary")
    results = workbook.create_sheet("Grid_Results")
    parameters = workbook.create_sheet("Parameter_Grid")
    definitions = workbook.create_sheet("Metric_Definitions")
    checks = workbook.create_sheet("Checks")

    _write_summary(summary, result)
    _write_grid_results(results, result)
    _write_parameter_grid(
        parameters,
        result,
    )
    _write_metric_definitions(definitions)
    _write_checks(checks, result)

    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=output.parent,
            prefix=f".{output.stem}.",
            suffix=".xlsx",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
        workbook.save(temporary_path)
        os.replace(temporary_path, output)
    finally:
        workbook.close()
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()
    return output


def _write_summary(sheet: Worksheet, result: GridBacktestResult) -> None:
    sheet.merge_cells("A1:F1")
    sheet["A1"] = (
        "Step 8 Grid Backtest — "
        f"{result.effective_start_date.isoformat()} to "
        f"{result.effective_end_date.isoformat()}"
    )
    sheet["A1"].fill = HEADER_FILL
    sheet["A1"].font = Font(color=WHITE, bold=True, size=15)
    sheet["A1"].alignment = Alignment(vertical="center")
    sheet.row_dimensions[1].height = 28

    _section(sheet, 3, "Grid overview", 6)
    overview = (
        ("Requested start", result.requested_start_date, "Requested end", result.requested_end_date),
        ("Effective start", result.effective_start_date, "Effective end", result.effective_end_date),
        ("Combinations", len(result.runs), "Successful", result.successful_run_count),
        ("Failed", result.failed_run_count, "Ranking", "Sharpe descending"),
        ("Best run", result.best_run_id, "Overall QC", result.overall_qc),
        ("Persistence", "Excel only", "DuckDB results", "not persisted"),
    )
    for row_number, values in enumerate(overview, start=4):
        for column, value in enumerate(values, start=1):
            sheet.cell(row_number, column, value=value)
        sheet.cell(row_number, 1).font = Font(bold=True)
        sheet.cell(row_number, 3).font = Font(bold=True)
    for cell in ("B4", "D4", "B5", "D5"):
        sheet[cell].number_format = DATE_FORMAT
    status_cell = sheet["D8"]
    status_cell.font = Font(
        bold=True,
        color=GREEN if result.overall_qc == "OK" else RED,
    )
    status_cell.fill = (
        OK_FILL if result.overall_qc == "OK" else CHECK_FILL
    )

    best = result.best_run
    _section(sheet, 11, "Best run", 6)
    best_rows = (
        ("Run ID", best.spec.run_id if best else None, "Rank", best.rank if best else None),
        ("w", best.spec.lookback_window if best else None, "p", best.spec.deviation_threshold if best else None),
        ("P", best.spec.variance_threshold if best else None, "l", best.spec.rebalance_period if best else None),
        ("q", best.spec.take_profit_threshold if best else None, "Status", best.status if best else None),
        ("Annualized return", _best_metric(best, "annualized_return"), "Sharpe", _best_metric(best, "sharpe_ratio")),
        ("Maximum drawdown", _best_metric(best, "maximum_drawdown"), "Calmar", _best_metric(best, "calmar_ratio")),
        ("SPY annualized return", _best_metric(best, "spy_annualized_return"), "Information ratio", _best_metric(best, "information_ratio")),
        ("Annualized turnover", _best_metric(best, "annualized_two_way_turnover"), "Run QC", _best_metric(best, "overall_qc")),
    )
    for row_number, values in enumerate(best_rows, start=12):
        for column, value in enumerate(values, start=1):
            sheet.cell(row_number, column, value=value)
        sheet.cell(row_number, 1).font = Font(bold=True)
        sheet.cell(row_number, 3).font = Font(bold=True)
    for cell in ("D13", "B14", "B15", "B16", "B17", "B18", "B19"):
        sheet[cell].number_format = PERCENT_FORMAT
    for cell in ("D16", "D17", "D18"):
        sheet[cell].number_format = RATIO_FORMAT

    _section(sheet, 22, "Top 10 by Sharpe", 10)
    top_headers = ("Rank", "Run ID", "w", "p", "P", "l", "q", "Annualized Return", "Sharpe", "Max Drawdown")
    top_runs = sorted(
        (run for run in result.runs if run.rank is not None),
        key=lambda run: int(run.rank),
    )[:10]
    _write_table(
        sheet,
        start_row=23,
        headers=top_headers,
        rows=(
            (
                run.rank,
                run.spec.run_id,
                run.spec.lookback_window,
                run.spec.deviation_threshold,
                run.spec.variance_threshold,
                run.spec.rebalance_period,
                run.spec.take_profit_threshold,
                run.metrics.annualized_return if run.metrics else None,
                run.metrics.sharpe_ratio if run.metrics else None,
                run.metrics.maximum_drawdown if run.metrics else None,
            )
            for run in top_runs
        ),
        number_formats={
            1: COUNT_FORMAT,
            3: COUNT_FORMAT,
            4: PERCENT_FORMAT,
            5: PERCENT_FORMAT,
            6: COUNT_FORMAT,
            7: PERCENT_FORMAT,
            8: PERCENT_FORMAT,
            9: RATIO_FORMAT,
            10: PERCENT_FORMAT,
        },
    )
    sheet.sheet_view.showGridLines = False
    sheet.freeze_panes = "A4"
    widths = (24, 22, 24, 22, 18, 18, 12, 12, 12, 18)
    for index, width in enumerate(widths, start=1):
        sheet.column_dimensions[get_column_letter(index)].width = width


def _write_grid_results(
    sheet: Worksheet,
    result: GridBacktestResult,
) -> None:
    headers = tuple(column[0] for column in RESULT_COLUMNS)
    rows = (
        tuple(accessor(run) for _, accessor, _, _ in RESULT_COLUMNS)
        for run in result.runs
    )
    formats = {
        index: number_format
        for index, (_, _, number_format, _) in enumerate(
            RESULT_COLUMNS,
            start=1,
        )
        if number_format is not None
    }
    _write_table(
        sheet,
        start_row=1,
        headers=headers,
        rows=rows,
        number_formats=formats,
    )
    for index, (_, _, _, width) in enumerate(RESULT_COLUMNS, start=1):
        sheet.column_dimensions[get_column_letter(index)].width = width
    sheet.freeze_panes = "K2"
    last_column = get_column_letter(len(RESULT_COLUMNS))
    sheet.auto_filter.ref = f"A1:{last_column}{sheet.max_row}"
    if sheet.max_row >= 2:
        sheet.conditional_formatting.add(
            f"C2:C{sheet.max_row}",
            FormulaRule(formula=['C2="SUCCESS"'], fill=OK_FILL),
        )
        sheet.conditional_formatting.add(
            f"C2:C{sheet.max_row}",
            FormulaRule(formula=['C2="FAILED"'], fill=CHECK_FILL),
        )
        sheet.conditional_formatting.add(
            f"A2:A{sheet.max_row}",
            FormulaRule(formula=["A2=1"], fill=BEST_FILL),
        )


def _write_parameter_grid(
    sheet: Worksheet,
    result: GridBacktestResult,
) -> None:
    _title(sheet, "Step 8 Parameter Grid", 5)
    _section(sheet, 3, "Search dimensions", 5)
    dimension_rows = (
        ("Parameter", "Symbol", "Candidate values", "Count", "Meaning"),
        ("Lookback window", "w", _joined(result.config.lookback_windows), len(result.config.lookback_windows), "Shared clustering and stock-selection sessions"),
        ("Deviation threshold", "p", _joined(result.config.deviation_thresholds), len(result.config.deviation_thresholds), "Winner/loser cumulative raw-return deviation threshold"),
        ("Variance threshold", "P", _joined(result.config.variance_thresholds), len(result.config.variance_thresholds), "Cumulative explained variance used to select K"),
        ("Rebalance period", "l", _joined(result.config.rebalance_periods), len(result.config.rebalance_periods), "Earned return sessions before scheduled rebalance"),
        ("Take-profit threshold", "q", _joined(result.config.take_profit_thresholds), len(result.config.take_profit_thresholds), "Compounded round return for early rebalance"),
    )
    for row_number, values in enumerate(dimension_rows, start=4):
        for column, value in enumerate(values, start=1):
            sheet.cell(row_number, column, value=value)
    _style_header(sheet, 4, 5)

    _section(sheet, 11, "Fixed settings", 5)
    fixed_rows = (
        ("Setting", "Value", "Unit / policy", "Source", "Notes"),
        ("Requested start", result.requested_start_date, "date", "GridBacktestConfig", "Explicit included return date"),
        ("Requested end", result.requested_end_date, "date", "GridBacktestConfig", "Explicit included return date"),
        ("Effective start", result.effective_start_date, "SPY session", "BacktestMarketDataRepository", "Requested start rolls forward"),
        ("Effective end", result.effective_end_date, "SPY session", "BacktestMarketDataRepository", "Must be an SPY session"),
        ("Beta window", result.beta_window, "sessions", "PreprocessingConfig", "Includes historical session t"),
        ("K estimation window", result.cluster_count_estimation_window, "sessions", "Grid fixed setting", "Independent of actual clustering w"),
        ("Initial NAV", result.config.initial_nav, "NAV units", "GridBacktestConfig", "Scale only"),
        ("Annualization", result.config.annualization_sessions, "sessions", "GridBacktestConfig", "Risk-free and cash return are zero"),
        ("tau positive", result.sponge_config.tau_positive, "SPONGE", "SpongeSymConfig", "Fixed across runs"),
        ("tau negative", result.sponge_config.tau_negative, "SPONGE", "SpongeSymConfig", "Fixed across runs"),
        ("Random seed", result.sponge_config.random_seed, "integer", "SpongeSymConfig", "Fixed across runs"),
        ("k-means n_init", result.sponge_config.kmeans_n_init, "runs", "SpongeSymConfig", "Fixed across runs"),
        ("Combinations", result.config.combination_count, "runs", "Cartesian product", "After sorting and de-duplication"),
        ("Maximum combinations", result.config.maximum_combinations, "runs", "Safety guard", "Must be explicitly raised when exceeded"),
    )
    for row_number, values in enumerate(fixed_rows, start=12):
        for column, value in enumerate(values, start=1):
            sheet.cell(row_number, column, value=value)
    _style_header(sheet, 12, 5)
    for row in (13, 14, 15, 16):
        sheet.cell(row, 2).number_format = DATE_FORMAT
    sheet.sheet_view.showGridLines = False
    sheet.freeze_panes = "A4"
    for column, width in enumerate((25, 24, 22, 27, 58), start=1):
        sheet.column_dimensions[get_column_letter(column)].width = width
    for row in range(1, sheet.max_row + 1):
        sheet.cell(row, 5).alignment = WRAPPED_ALIGNMENT


def _write_metric_definitions(sheet: Worksheet) -> None:
    _title(sheet, "Metric Definitions", 5)
    rows = _metric_definition_rows()
    _write_table(
        sheet,
        start_row=3,
        headers=("Metric", "Category", "Definition", "Unit", "Undefined rule"),
        rows=rows,
    )
    sheet.freeze_panes = "A4"
    sheet.sheet_view.showGridLines = False
    for column, width in enumerate((31, 20, 90, 24, 48), start=1):
        sheet.column_dimensions[get_column_letter(column)].width = width
    for row in range(4, sheet.max_row + 1):
        sheet.cell(row, 3).alignment = WRAPPED_ALIGNMENT
        sheet.cell(row, 5).alignment = WRAPPED_ALIGNMENT


def _write_checks(sheet: Worksheet, result: GridBacktestResult) -> None:
    _title(sheet, "Grid Backtest Checks", 8)
    successful_sessions = {
        run.metrics.session_count
        for run in result.runs
        if run.metrics is not None
    }
    unique_ids = len({run.spec.run_id for run in result.runs})
    summary_checks = (
        ("Combination count", len(result.runs), result.config.combination_count, len(result.runs) - result.config.combination_count, 0, "OK" if len(result.runs) == result.config.combination_count else "CHECK", "One result row per Cartesian-product combination"),
        ("Unique run IDs", unique_ids, len(result.runs), unique_ids - len(result.runs), 0, "OK" if unique_ids == len(result.runs) else "CHECK", "Stable run IDs must be unique"),
        ("Successful session alignment", len(successful_sessions), 1, len(successful_sessions) - 1, 0, "OK" if len(successful_sessions) <= 1 else "CHECK", "All successful combinations must use the same return sessions"),
        ("Failed runs", result.failed_run_count, 0, result.failed_run_count, 0, "OK" if result.failed_run_count == 0 else "CHECK", "Failures remain visible and are excluded from ranking"),
        ("Overall QC", result.overall_qc, "OK", None, None, result.overall_qc, "Aggregates run status, NAV/exposure reconciliation and FIFO"),
    )
    _write_table(
        sheet,
        start_row=3,
        headers=("Check", "Actual", "Expected", "Difference", "Tolerance", "Status", "Notes"),
        rows=summary_checks,
    )
    _section(sheet, 11, "Run-level audit", 8)
    _write_table(
        sheet,
        start_row=12,
        headers=(
            "Run ID",
            "Status",
            "Rank",
            "Sessions",
            "FIFO",
            "Run QC",
            "Error Type",
            "Error Message",
        ),
        rows=(
            (
                run.spec.run_id,
                run.status,
                run.rank,
                run.metrics.session_count if run.metrics else None,
                run.metrics.fifo_reconciliation_status if run.metrics else None,
                run.metrics.overall_qc if run.metrics else None,
                run.error_type,
                run.error_message,
            )
            for run in result.runs
        ),
        number_formats={3: COUNT_FORMAT, 4: COUNT_FORMAT},
    )
    sheet.freeze_panes = "A13"
    sheet.sheet_view.showGridLines = False
    for column, width in enumerate((32, 14, 14, 14, 14, 14, 20, 62), start=1):
        sheet.column_dimensions[get_column_letter(column)].width = width
    for row in range(4, sheet.max_row + 1):
        sheet.cell(row, 1).alignment = WRAPPED_ALIGNMENT
        sheet.cell(row, 8).alignment = WRAPPED_ALIGNMENT
    if sheet.max_row >= 13:
        sheet.conditional_formatting.add(
            f"B13:B{sheet.max_row}",
            FormulaRule(formula=['B13="SUCCESS"'], fill=OK_FILL),
        )
        sheet.conditional_formatting.add(
            f"B13:B{sheet.max_row}",
            FormulaRule(formula=['B13="FAILED"'], fill=CHECK_FILL),
        )


def _write_table(
    sheet: Worksheet,
    *,
    start_row: int,
    headers: Sequence[str],
    rows: Iterable[Sequence[object]],
    number_formats: dict[int, str] | None = None,
) -> None:
    formats = number_formats or {}
    for column, value in enumerate(headers, start=1):
        cell = sheet.cell(start_row, column, value=value)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = HEADER_ALIGNMENT
        cell.border = HEADER_BORDER
    for row_number, values in enumerate(rows, start=start_row + 1):
        row_values = tuple(values)
        if len(row_values) != len(headers):
            raise ValueError("Excel row does not match its header count")
        for column, value in enumerate(row_values, start=1):
            cell = sheet.cell(row_number, column, value=value)
            if (row_number - start_row) % 2 == 1:
                cell.fill = STRIPE_FILL
            if column in formats:
                cell.number_format = formats[column]
    sheet.row_dimensions[start_row].height = 34
    last_column = sheet.cell(start_row, len(headers)).column_letter
    sheet.auto_filter.ref = (
        f"A{start_row}:{last_column}{max(sheet.max_row, start_row)}"
    )


def _title(sheet: Worksheet, value: str, columns: int) -> None:
    sheet.merge_cells(
        start_row=1,
        start_column=1,
        end_row=1,
        end_column=columns,
    )
    cell = sheet.cell(1, 1, value=value)
    cell.fill = HEADER_FILL
    cell.font = Font(color=WHITE, bold=True, size=15)
    cell.alignment = Alignment(vertical="center")
    sheet.row_dimensions[1].height = 28


def _section(
    sheet: Worksheet,
    row: int,
    label: str,
    columns: int,
) -> None:
    sheet.merge_cells(
        start_row=row,
        start_column=1,
        end_row=row,
        end_column=columns,
    )
    cell = sheet.cell(row, 1, value=label)
    cell.fill = SECTION_FILL
    cell.font = Font(bold=True, color=NAVY)
    cell.border = HEADER_BORDER


def _style_header(sheet: Worksheet, row: int, columns: int) -> None:
    for column in range(1, columns + 1):
        cell = sheet.cell(row, column)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = HEADER_ALIGNMENT
        cell.border = HEADER_BORDER


def _best_metric(
    run: GridRunResult | None,
    attribute: str,
) -> object:
    if run is None or run.metrics is None:
        return None
    return getattr(run.metrics, attribute)


def _joined(values: Sequence[object]) -> str:
    return ", ".join(map(str, values))


def _metric_definition_rows() -> tuple[tuple[str, str, str, str, str], ...]:
    explicit = {
        "annualized_return": ("Return", "(ending NAV / starting NAV)^(annualization sessions / observed sessions) - 1", "annual rate", "Blank unless both NAV values are positive"),
        "annualized_volatility": ("Risk", "Sample standard deviation of daily returns × sqrt(annualization sessions)", "annual rate", "Blank when daily volatility is zero or fewer than two observations"),
        "sharpe_ratio": ("Risk-adjusted", "Mean daily return / sample daily volatility × sqrt(annualization sessions); risk-free rate is zero", "ratio", "Blank when daily volatility is zero"),
        "annualized_downside_volatility": ("Risk", "Sample standard deviation of negative daily returns × sqrt(annualization sessions)", "annual rate", "Blank with fewer than two negative returns or zero downside volatility"),
        "sortino_ratio": ("Risk-adjusted", "Mean daily return / sample standard deviation of negative daily returns × sqrt(annualization sessions)", "ratio", "Blank with fewer than two negative returns or zero downside volatility"),
        "maximum_drawdown": ("Risk", "Minimum signed NAV / running peak NAV - 1, including starting NAV", "return", "Zero when no drawdown occurs"),
        "calmar_ratio": ("Risk-adjusted", "Annualized return / absolute maximum drawdown", "ratio", "Blank when maximum drawdown is zero or annualized return is undefined"),
        "daily_var_95": ("Tail risk", "Historical 5th percentile of daily returns using linear interpolation", "daily return", "Always defined for a successful run"),
        "daily_cvar_95": ("Tail risk", "Mean daily return at or below the historical 5th percentile", "daily return", "Always defined for a successful run"),
        "spy_beta": ("Benchmark", "Sample covariance(strategy, SPY) / sample variance(SPY)", "ratio", "Blank when SPY variance is zero"),
        "annualized_alpha": ("Benchmark", "252 × [mean(strategy return) - beta × mean(SPY return)]; risk-free rate is zero", "annual rate", "Blank when beta is undefined"),
        "tracking_error": ("Benchmark", "Sample standard deviation of strategy minus SPY daily return × sqrt(annualization sessions)", "annual rate", "Blank when active-return volatility is zero"),
        "information_ratio": ("Benchmark", "Mean active daily return / sample active-return volatility × sqrt(annualization sessions)", "ratio", "Blank when active-return volatility is zero"),
        "annualized_two_way_turnover": ("Operations", "0.5 × sum(executed non-initial trade notional / trade-date NAV) × annualization sessions / observed sessions", "annual rate", "Zero when no post-initial trades execute"),
        "overall_qc": ("Audit", "OK only when daily values are finite, cash plus gross exposure reconciles to one, and FIFO status is OK", "status", "CHECK identifies a run requiring review"),
    }
    rows: list[tuple[str, str, str, str, str]] = []
    for metric_field in fields(GridRunMetrics):
        name = metric_field.name
        category, definition, unit, undefined = explicit.get(
            name,
            _default_metric_definition(name),
        )
        rows.append(
            (
                name,
                category,
                definition,
                unit,
                undefined,
            )
        )
    return tuple(rows)


def _default_metric_definition(
    name: str,
) -> tuple[str, str, str, str]:
    definitions = {
        "session_count": ("Setup", "Number of aligned strategy and SPY return sessions", "count", "Never blank for a successful run"),
        "starting_nav": ("Return", "Configured initial NAV", "NAV", "Never blank"),
        "ending_nav": ("Return", "Final strategy NAV after the last included return", "NAV", "Never blank"),
        "total_return": ("Return", "Ending NAV / starting NAV - 1", "return", "Never blank"),
        "mean_daily_return": ("Return", "Arithmetic mean of daily strategy returns", "daily return", "Never blank"),
        "drawdown_peak_date": ("Risk", "Date of the NAV peak preceding maximum drawdown", "date", "Blank when no drawdown occurs"),
        "drawdown_trough_date": ("Risk", "Date of the maximum-drawdown trough", "date", "Blank when no drawdown occurs"),
        "drawdown_recovery_date": ("Risk", "First later date NAV recovers the prior peak", "date", "Blank when not recovered or no drawdown occurs"),
        "win_rate": ("Distribution", "Positive-return sessions / all sessions", "rate", "Never blank"),
        "payoff_ratio": ("Distribution", "Average positive return / absolute average negative return", "ratio", "Blank without both positive and negative sessions"),
        "profit_factor": ("Distribution", "Sum of positive returns / absolute sum of negative returns", "ratio", "Blank without negative sessions"),
        "skewness": ("Distribution", "Bias-corrected sample skewness of daily returns", "ratio", "Blank with fewer than three sessions"),
        "excess_kurtosis": ("Distribution", "Bias-corrected sample excess kurtosis of daily returns", "ratio", "Blank with fewer than four sessions"),
        "spy_correlation": ("Benchmark", "Sample daily return correlation between strategy and SPY", "ratio", "Blank when either series has zero volatility"),
        "excess_total_return": ("Benchmark", "Strategy total return minus SPY total return", "return", "Never blank"),
        "excess_annualized_return": ("Benchmark", "Strategy annualized return minus SPY annualized return", "annual rate", "Blank when either annualized return is undefined"),
        "average_held_sessions": ("Operations", "Mean held_sessions across non-initial rebalance events", "sessions", "Blank when no later rebalance occurs"),
        "fifo_reconciliation_status": ("Audit", "FIFO buy-lot and sell-unit reconciliation status from step 7", "status", "Never blank for a successful run"),
    }
    if name in definitions:
        return definitions[name]
    if name.startswith("spy_"):
        return ("SPY benchmark", f"SPY counterpart of {name[4:].replace('_', ' ')}", "same as strategy metric", "Uses the same undefined rule as the strategy metric")
    if "count" in name or name.endswith("_sessions") or name.endswith("_events"):
        return ("Operations", name.replace("_", " ").capitalize(), "count", "Never blank for a successful run")
    if any(token in name for token in ("return", "volatility", "drawdown", "rate", "exposure", "weight", "turnover", "alpha", "error")):
        return ("Calculated output", name.replace("_", " ").capitalize(), "rate", "See related denominator or sample-size rule")
    return ("Calculated output", name.replace("_", " ").capitalize(), "value", "Never blank unless the required sample is unavailable")

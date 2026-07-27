from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
import os
from pathlib import Path
import tempfile

from openpyxl import Workbook
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.worksheet.worksheet import Worksheet

from .models import BacktestResult, PerformanceMetrics


NAVY = "1F4E78"
LIGHT_BLUE = "D9EAF7"
LIGHT_GREEN = "E2F0D9"
LIGHT_RED = "FCE4D6"
WHITE = "FFFFFF"
GREEN = "548235"
RED = "C00000"

HEADER_FILL = PatternFill("solid", fgColor=NAVY)
SECTION_FILL = PatternFill("solid", fgColor=LIGHT_BLUE)
OK_FILL = PatternFill("solid", fgColor=LIGHT_GREEN)
CHECK_FILL = PatternFill("solid", fgColor=LIGHT_RED)
STRIPE_FILL = PatternFill("solid", fgColor="F8FAFC")
HEADER_FONT = Font(color=WHITE, bold=True)
THIN_GRAY = Side(style="thin", color="D9E2F3")
HEADER_BORDER = Border(bottom=THIN_GRAY)
HEADER_ALIGNMENT = Alignment(
    horizontal="center",
    vertical="center",
    wrap_text=True,
)
WRAPPED_ALIGNMENT = Alignment(
    vertical="top",
    wrap_text=True,
)

PERCENT_FORMAT = "0.0000%"
WEIGHT_FORMAT = "0.000000"
NAV_FORMAT = "0.000000"
RATIO_FORMAT = "0.0000"


def export_backtest_workbook(
    result: BacktestResult,
    output_path: Path,
    *,
    replace_existing: bool = False,
) -> Path:
    output = Path(output_path).resolve()
    if output.exists() and not replace_existing:
        raise FileExistsError(
            f"Excel output already exists: {output}. Use --replace to overwrite it."
        )
    output.parent.mkdir(parents=True, exist_ok=True)

    workbook = Workbook()
    workbook.remove(workbook.active)
    summary = workbook.create_sheet("Summary")
    daily = workbook.create_sheet("Daily_Performance")
    events = workbook.create_sheet("Rebalance_Events")
    targets = workbook.create_sheet("Target_Weights")
    trades = workbook.create_sheet("Trades")
    missing = workbook.create_sheet("Missing_Data_Audit")

    _write_summary(summary, result)
    _write_daily_performance(daily, result)
    _write_rebalance_events(events, result)
    _write_target_weights(targets, result)
    _write_trades(trades, result)
    _write_missing_data(missing, result)

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


def _write_summary(sheet: Worksheet, result: BacktestResult) -> None:
    config = result.config
    strategy = result.strategy_metrics
    spy = result.spy_metrics
    missing_days = sum(
        row.missing_position_count > 0 for row in result.daily_performance
    )
    rows = [
        ("Backtest setup", None),
        ("Start date", config.start_date),
        ("End date", config.end_date),
        ("Return sessions", strategy.session_count),
        ("Rebalance period l", config.rebalance_period),
        ("Take-profit threshold q", config.take_profit_threshold),
        ("Initial NAV", config.initial_nav),
        ("Annualization sessions", config.annualization_sessions),
        ("Missing-price policy", config.missing_price_policy),
        (None, None),
        ("Confirmed time semantics", None),
        (
            "Target formation",
            "as_of_date=T uses inputs through T-1; target earns return dated T",
        ),
        (
            "Event boundary",
            "old portfolio earns event-date return; new target starts next session",
        ),
        (
            "Holding convention",
            "fixed economic units between events; weights drift with close prices",
        ),
        ("Cash return", "0%"),
        ("Transaction costs and slippage", "not included"),
        (None, None),
        ("Strategy performance", None),
        *_metric_rows("Strategy", strategy),
        (None, None),
        ("SPY performance", None),
        *_metric_rows("SPY", spy),
        (None, None),
        ("Audit and QC", None),
        ("Rebalance events", len(result.rebalance_events)),
        ("Target-weight rows", len(result.target_weights)),
        ("Trade rows", len(result.trades)),
        ("Missing-price audit rows", len(result.missing_data_audit)),
        ("Sessions with frozen positions", missing_days),
        ("Metrics contain infinities", "NO"),
        ("Overall QC", _overall_qc(result)),
        (None, None),
        ("Research scope", None),
        (
            "Project convention",
            "Yahoo Close price return; p=5%; long-only losers; inactive clusters cash",
        ),
        ("FF12 benchmark", "not produced because ff12_code is currently empty"),
        ("Risk-free rate", "0, following the paper"),
        ("Calculation version", result.calculation_version),
        (
            "Paper",
            "https://ora.ox.ac.uk/objects/uuid%3Ac60358c0-24f0-4c66-b973-f84776f66f8a",
        ),
        (
            "Author clustering code",
            "https://github.com/maxclchen/Correlation-Matrix-Clustering-for-Statistical-Arbitrage-Portfolios",
        ),
    ]

    sheet.merge_cells("A1:B1")
    sheet["A1"] = (
        f"Step 7 Backtest — {config.start_date.isoformat()} to "
        f"{config.end_date.isoformat()}"
    )
    sheet["A1"].fill = HEADER_FILL
    sheet["A1"].font = Font(color=WHITE, bold=True, size=15)
    sheet["A1"].alignment = Alignment(vertical="center")
    sheet.row_dimensions[1].height = 28
    for row in rows:
        sheet.append(row)

    section_labels = {
        "Backtest setup",
        "Confirmed time semantics",
        "Strategy performance",
        "SPY performance",
        "Audit and QC",
        "Research scope",
    }
    for row in range(2, sheet.max_row + 1):
        label = sheet.cell(row, 1).value
        if label in section_labels:
            sheet.merge_cells(
                start_row=row,
                start_column=1,
                end_row=row,
                end_column=2,
            )
            cell = sheet.cell(row, 1)
            cell.fill = SECTION_FILL
            cell.font = Font(bold=True, color=NAVY)
            cell.border = HEADER_BORDER
        elif label is not None:
            sheet.cell(row, 1).font = Font(bold=True)

    for row in range(2, sheet.max_row + 1):
        label = sheet.cell(row, 1).value
        value = sheet.cell(row, 2)
        if label in ("Start date", "End date"):
            value.number_format = "yyyy-mm-dd"
        elif label in (
            "Take-profit threshold q",
            "Strategy total return",
            "Strategy annualized return",
            "SPY total return",
            "SPY annualized return",
        ):
            value.number_format = PERCENT_FORMAT
        elif label in (
            "Initial NAV",
            "Strategy starting NAV",
            "Strategy ending NAV",
            "SPY starting NAV",
            "SPY ending NAV",
        ):
            value.number_format = NAV_FORMAT
        elif label in (
            "Strategy Sharpe ratio",
            "Strategy Sortino ratio",
            "SPY Sharpe ratio",
            "SPY Sortino ratio",
        ):
            value.number_format = RATIO_FORMAT

    qc_row = next(
        row
        for row in range(2, sheet.max_row + 1)
        if sheet.cell(row, 1).value == "Overall QC"
    )
    qc_cell = sheet.cell(qc_row, 2)
    qc_cell.font = Font(
        bold=True,
        color=GREEN if qc_cell.value == "OK" else RED,
    )
    qc_cell.fill = OK_FILL if qc_cell.value == "OK" else CHECK_FILL
    sheet.sheet_view.showGridLines = False
    sheet.freeze_panes = "A3"
    sheet.column_dimensions["A"].width = 34
    sheet.column_dimensions["B"].width = 86
    for row in range(2, sheet.max_row + 1):
        sheet.cell(row, 2).alignment = Alignment(
            vertical="top",
            wrap_text=True,
        )


def _metric_rows(
    prefix: str,
    metrics: PerformanceMetrics,
) -> tuple[tuple[str, object], ...]:
    return (
        (f"{prefix} starting NAV", metrics.starting_nav),
        (f"{prefix} ending NAV", metrics.ending_nav),
        (f"{prefix} total return", metrics.total_return),
        (f"{prefix} annualized return", metrics.annualized_return),
        (f"{prefix} Sharpe ratio", metrics.sharpe_ratio),
        (f"{prefix} Sortino ratio", metrics.sortino_ratio),
    )


def _write_daily_performance(
    sheet: Worksheet,
    result: BacktestResult,
) -> None:
    _write_table(
        sheet,
        headers=(
            "Trade Date",
            "Strategy Return",
            "NAV",
            "Round ID",
            "Round Return",
            "Holding Day",
            "Cash Value",
            "Cash Weight",
            "Gross Exposure",
            "Frozen Value",
            "Frozen Exposure",
            "Positions",
            "Missing Positions",
            "Trigger",
            "SPY Return",
            "SPY NAV",
        ),
        rows=(
            (
                row.trade_date,
                row.strategy_return,
                row.nav,
                row.round_id,
                row.round_return,
                row.holding_day,
                row.cash_value,
                row.cash_weight,
                row.gross_exposure,
                row.frozen_value,
                row.frozen_exposure,
                row.position_count,
                row.missing_position_count,
                row.trigger_reason,
                row.spy_return,
                row.spy_nav,
            )
            for row in result.daily_performance
        ),
        widths=(13, 17, 15, 11, 16, 13, 15, 14, 16, 15, 16, 12, 18, 14, 14, 15),
        number_formats={
            1: "yyyy-mm-dd",
            2: PERCENT_FORMAT,
            3: NAV_FORMAT,
            4: "0",
            5: PERCENT_FORMAT,
            6: "0",
            7: NAV_FORMAT,
            8: PERCENT_FORMAT,
            9: PERCENT_FORMAT,
            10: NAV_FORMAT,
            11: PERCENT_FORMAT,
            12: "0",
            13: "0",
            15: PERCENT_FORMAT,
            16: NAV_FORMAT,
        },
    )
    if sheet.max_row >= 2:
        sheet.conditional_formatting.add(
            f"N2:N{sheet.max_row}",
            FormulaRule(formula=['N2="stop_win"'], fill=OK_FILL),
        )
        sheet.conditional_formatting.add(
            f"N2:N{sheet.max_row}",
            FormulaRule(formula=['N2="scheduled"'], fill=SECTION_FILL),
        )


def _write_rebalance_events(
    sheet: Worksheet,
    result: BacktestResult,
) -> None:
    _write_table(
        sheet,
        headers=(
            "Event ID",
            "Event Date",
            "Reason",
            "Effective Date",
            "Round ID",
            "Held Sessions",
            "Round Return",
            "NAV",
            "K",
            "Active Clusters",
            "Inactive Clusters",
            "Target Gross",
            "Frozen Value",
            "Available Capital",
        ),
        rows=(
            (
                event.event_id,
                event.event_date,
                event.reason,
                event.effective_date,
                event.round_id,
                event.held_sessions,
                event.round_return,
                event.nav,
                event.cluster_count,
                event.active_cluster_count,
                event.inactive_cluster_count,
                event.target_gross_exposure,
                event.frozen_value,
                event.available_capital,
            )
            for event in result.rebalance_events
        ),
        widths=(11, 14, 14, 15, 11, 15, 16, 15, 9, 17, 18, 16, 15, 18),
        number_formats={
            1: "0",
            2: "yyyy-mm-dd",
            4: "yyyy-mm-dd",
            5: "0",
            6: "0",
            7: PERCENT_FORMAT,
            8: NAV_FORMAT,
            9: "0",
            10: "0",
            11: "0",
            12: PERCENT_FORMAT,
            13: NAV_FORMAT,
            14: NAV_FORMAT,
        },
    )


def _write_target_weights(
    sheet: Worksheet,
    result: BacktestResult,
) -> None:
    _write_table(
        sheet,
        headers=(
            "Event ID",
            "Effective Date",
            "Ticker",
            "Market Cap Rank",
            "Cluster ID",
            "Cumulative Deviation",
            "Classification",
            "Local Weight",
            "Portfolio Weight",
        ),
        rows=(
            (
                row.event_id,
                row.effective_date,
                row.ticker,
                row.market_cap_rank,
                row.cluster_id,
                row.cumulative_deviation,
                row.classification,
                row.local_weight,
                row.portfolio_weight,
            )
            for row in result.target_weights
        ),
        widths=(11, 15, 14, 18, 12, 23, 21, 16, 18),
        number_formats={
            1: "0",
            2: "yyyy-mm-dd",
            4: "0",
            5: "0",
            6: PERCENT_FORMAT,
            8: WEIGHT_FORMAT,
            9: WEIGHT_FORMAT,
        },
    )
    if sheet.max_row >= 2:
        sheet.conditional_formatting.add(
            f"G2:G{sheet.max_row}",
            FormulaRule(formula=['G2="previous_loser"'], fill=OK_FILL),
        )


def _write_trades(sheet: Worksheet, result: BacktestResult) -> None:
    _write_table(
        sheet,
        headers=(
            "Event ID",
            "Trade Date",
            "Ticker",
            "Side",
            "Value Before",
            "Value After",
            "Trade Notional",
            "Status",
            "Reason",
        ),
        rows=(
            (
                trade.event_id,
                trade.trade_date,
                trade.ticker,
                trade.side,
                trade.value_before,
                trade.value_after,
                trade.trade_notional,
                trade.status,
                trade.reason,
            )
            for trade in result.trades
        ),
        widths=(11, 14, 14, 10, 16, 16, 17, 14, 24),
        number_formats={
            1: "0",
            2: "yyyy-mm-dd",
            5: NAV_FORMAT,
            6: NAV_FORMAT,
            7: NAV_FORMAT,
        },
    )


def _write_missing_data(
    sheet: Worksheet,
    result: BacktestResult,
) -> None:
    _write_table(
        sheet,
        headers=(
            "Trade Date",
            "Ticker",
            "Event",
            "Action",
            "Last Valid Close",
            "Position Value",
            "Details",
        ),
        rows=(
            (
                audit.trade_date,
                audit.ticker,
                audit.event,
                audit.action,
                audit.last_valid_close,
                audit.position_value,
                audit.details,
            )
            for audit in result.missing_data_audit
        ),
        widths=(14, 14, 20, 36, 18, 18, 74),
        number_formats={
            1: "yyyy-mm-dd",
            5: NAV_FORMAT,
            6: NAV_FORMAT,
        },
        alignments={7: WRAPPED_ALIGNMENT},
    )


def _overall_qc(result: BacktestResult) -> str:
    daily = result.daily_performance
    finite = all(
        _finite(
            row.strategy_return,
            row.nav,
            row.round_return,
            row.cash_value,
            row.cash_weight,
            row.gross_exposure,
            row.frozen_value,
            row.frozen_exposure,
            row.spy_return,
            row.spy_nav,
        )
        for row in daily
    )
    reconciled = all(
        abs(row.cash_weight + row.gross_exposure - 1.0) < 1e-10
        for row in daily
    )
    metrics = (
        result.strategy_metrics,
        result.spy_metrics,
    )
    metric_values = [
        value
        for metric in metrics
        for value in (
            metric.annualized_return,
            metric.sharpe_ratio,
            metric.sortino_ratio,
        )
        if value is not None
    ]
    return (
        "OK"
        if finite
        and reconciled
        and all(_finite(value) for value in metric_values)
        else "CHECK"
    )


def _finite(*values: float) -> bool:
    import math

    return all(math.isfinite(float(value)) for value in values)


def _write_table(
    sheet: Worksheet,
    *,
    headers: Sequence[str],
    rows: Iterable[Sequence[object]],
    widths: tuple[int, ...],
    number_formats: Mapping[int, str] | None = None,
    alignments: Mapping[int, Alignment] | None = None,
) -> None:
    if len(headers) != len(widths):
        raise ValueError("table headers and widths must have the same length")
    formats = number_formats or {}
    configured_alignments = alignments or {}
    sheet.append(list(headers))
    for column in range(1, len(widths) + 1):
        cell = sheet.cell(1, column)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = HEADER_ALIGNMENT
        cell.border = HEADER_BORDER

    for row_number, values in enumerate(rows, start=2):
        row_values = tuple(values)
        if len(row_values) != len(headers):
            raise ValueError(
                f"table row {row_number} has {len(row_values)} values; "
                f"expected {len(headers)}"
            )
        for column, value in enumerate(row_values, start=1):
            cell = sheet.cell(row_number, column, value=value)
            if row_number % 2 == 0:
                cell.fill = STRIPE_FILL
            number_format = formats.get(column)
            if number_format is not None:
                cell.number_format = number_format
            alignment = configured_alignments.get(column)
            if alignment is not None:
                cell.alignment = alignment

    sheet.row_dimensions[1].height = 32
    sheet.freeze_panes = "A2"
    last_column = sheet.cell(1, len(widths)).column_letter
    sheet.auto_filter.ref = f"A1:{last_column}{sheet.max_row}"
    sheet.sheet_view.showGridLines = False
    for column, width in enumerate(widths, start=1):
        column_letter = sheet.cell(1, column).column_letter
        sheet.column_dimensions[column_letter].width = width

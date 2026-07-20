from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
from openpyxl.formatting.rule import ColorScaleRule, FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from .models import PreprocessingSnapshot


HEADER_FILL = PatternFill("solid", fgColor="1F4E78")
SECTION_FILL = PatternFill("solid", fgColor="D9EAF7")
DIAGONAL_FILL = PatternFill("solid", fgColor="E7E6E6")
HEADER_FONT = Font(color="FFFFFF", bold=True)
THIN_GRAY = Side(style="thin", color="D9E2F3")


def export_snapshot_workbook(
    snapshot: PreprocessingSnapshot,
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
    parameters = workbook.create_sheet("Parameters_QC")
    beta = workbook.create_sheet("Beta_Used")
    returns = workbook.create_sheet("Stock_Returns")
    residual = workbook.create_sheet("Residual_Matrix")
    correlation = workbook.create_sheet("Correlation_Matrix")
    excluded = workbook.create_sheet("Excluded_Stocks")

    _write_parameters(parameters, snapshot)
    _write_wide_matrix(beta, snapshot.beta_matrix, "Trade Date")
    _write_stock_returns(returns, snapshot)
    _write_wide_matrix(residual, snapshot.residual_matrix, "Trade Date")
    _write_correlation(correlation, snapshot)
    _write_exclusions(excluded, snapshot)

    workbook.calculation.fullCalcOnLoad = True
    workbook.calculation.forceFullCalc = True
    workbook.save(output)
    return output


def _write_parameters(sheet: Worksheet, snapshot: PreprocessingSnapshot) -> None:
    rows = [
        ("Parameter / QC", "Program Value", "Excel Check", "Difference"),
        ("As-of date", snapshot.as_of_date, None, None),
        ("Residual window start", snapshot.window_start, None, None),
        ("Residual window end", snapshot.window_end, None, None),
        ("Preprocessing run id", snapshot.preprocessing_run_id, None, None),
        ("Snapshot id", snapshot.snapshot_id, None, None),
        ("Return basis", snapshot.return_basis, None, None),
        ("Beta window", snapshot.beta_window, None, None),
        ("Correlation window", snapshot.correlation_window, None, None),
        ("Beta alignment", snapshot.beta_alignment, None, None),
        ("Missing policy", snapshot.missing_policy, None, None),
        ("Calculation version", snapshot.calculation_version, None, None),
        ("Variance epsilon", snapshot.variance_epsilon, None, None),
        ("Selected stocks", snapshot.selected_stock_count, None, None),
        ("Valid stocks", snapshot.valid_stock_count, None, None),
        ("Excluded stocks", snapshot.excluded_stock_count, None, None),
        ("Maximum asymmetry", snapshot.quality.maximum_asymmetry, None, None),
        ("Minimum correlation", snapshot.quality.minimum_correlation, None, None),
        ("Maximum correlation", snapshot.quality.maximum_correlation, None, None),
        ("Minimum eigenvalue", snapshot.quality.minimum_eigenvalue, None, None),
        ("Numerical rank", snapshot.quality.numerical_rank, None, None),
        (
            "Contains non-finite values",
            "TRUE" if snapshot.quality.has_non_finite_values else "FALSE",
            None,
            None,
        ),
    ]
    for row in rows:
        sheet.append(row)

    check_start = len(rows) + 2
    first_ticker = snapshot.tickers[0]
    second_ticker = snapshot.tickers[1]
    first_residual = float(snapshot.residual_matrix.iloc[0, 0])
    first_correlation = float(snapshot.correlation_matrix.iloc[0, 1])
    sheet.cell(check_start, 1, f"Residual identity sample: {first_ticker}")
    sheet.cell(check_start, 2, first_residual)
    sheet.cell(
        check_start,
        3,
        "='Stock_Returns'!C2-'Beta_Used'!B2*'Stock_Returns'!B2",
    )
    sheet.cell(check_start, 4, f"=C{check_start}-B{check_start}")
    sheet.cell(check_start + 1, 1, f"Correlation sample: {first_ticker}/{second_ticker}")
    sheet.cell(check_start + 1, 2, first_correlation)
    last_residual_row = len(snapshot.residual_matrix.index) + 1
    sheet.cell(
        check_start + 1,
        3,
        f"=CORREL('Residual_Matrix'!B2:B{last_residual_row},"
        f"'Residual_Matrix'!C2:C{last_residual_row})",
    )
    sheet.cell(check_start + 1, 4, f"=C{check_start + 1}-B{check_start + 1}")

    _style_header(sheet, 1, 4)
    row_by_label = {
        str(sheet.cell(row_number, 1).value): row_number
        for row_number in range(2, sheet.max_row + 1)
        if sheet.cell(row_number, 1).value is not None
    }
    for label in ("As-of date", "Residual window start", "Residual window end"):
        sheet.cell(row_by_label[label], 2).number_format = "yyyy-mm-dd"
    for label in (
        "Beta window",
        "Correlation window",
        "Selected stocks",
        "Valid stocks",
        "Excluded stocks",
        "Numerical rank",
    ):
        sheet.cell(row_by_label[label], 2).number_format = "0"
    for label in (
        "Maximum asymmetry",
        "Minimum correlation",
        "Maximum correlation",
    ):
        sheet.cell(row_by_label[label], 2).number_format = "0.0000000000"
    sheet.cell(row_by_label["Variance epsilon"], 2).number_format = "0.000000E+00"
    sheet.cell(row_by_label["Minimum eigenvalue"], 2).number_format = "0.000000E+00"
    sheet.cell(row_by_label["Contains non-finite values"], 2).number_format = "General"
    for row_number in (check_start, check_start + 1):
        for column in (2, 3, 4):
            sheet.cell(row_number, column).number_format = "0.0000000000"
    sheet.freeze_panes = "A2"
    sheet.sheet_view.showGridLines = False
    sheet.column_dimensions["A"].width = 38
    sheet.column_dimensions["B"].width = 28
    sheet.column_dimensions["C"].width = 22
    sheet.column_dimensions["D"].width = 18


def _write_wide_matrix(sheet: Worksheet, frame, index_label: str) -> None:
    sheet.append([index_label, *map(str, frame.columns)])
    for index, row in frame.iterrows():
        sheet.append([index.to_pydatetime(), *[float(value) for value in row]])
    _style_header(sheet, 1, len(frame.columns) + 1)
    sheet.freeze_panes = "B2"
    sheet.sheet_view.showGridLines = False
    sheet.column_dimensions["A"].width = 13
    for column in range(2, len(frame.columns) + 2):
        letter = get_column_letter(column)
        sheet.column_dimensions[letter].width = 11
        for row in range(2, len(frame.index) + 2):
            sheet.cell(row, column).number_format = "0.000000"
    for row in range(2, len(frame.index) + 2):
        sheet.cell(row, 1).number_format = "yyyy-mm-dd"


def _write_stock_returns(sheet: Worksheet, snapshot: PreprocessingSnapshot) -> None:
    sheet.append(["Trade Date", "SPY", *snapshot.tickers])
    for trade_date in snapshot.stock_return_matrix.index:
        sheet.append(
            [
                trade_date.to_pydatetime(),
                float(snapshot.market_returns.loc[trade_date]),
                *[
                    float(snapshot.stock_return_matrix.loc[trade_date, ticker])
                    for ticker in snapshot.tickers
                ],
            ]
        )
    _style_header(sheet, 1, len(snapshot.tickers) + 2)
    sheet.freeze_panes = "C2"
    sheet.sheet_view.showGridLines = False
    sheet.column_dimensions["A"].width = 13
    for column in range(2, len(snapshot.tickers) + 3):
        sheet.column_dimensions[get_column_letter(column)].width = 11
        for row in range(2, len(snapshot.stock_return_matrix.index) + 2):
            sheet.cell(row, column).number_format = "0.000000"
    for row in range(2, len(snapshot.stock_return_matrix.index) + 2):
        sheet.cell(row, 1).number_format = "yyyy-mm-dd"


def _write_correlation(sheet: Worksheet, snapshot: PreprocessingSnapshot) -> None:
    sheet.append(["Ticker", *snapshot.tickers])
    for ticker, row in snapshot.correlation_matrix.iterrows():
        sheet.append([str(ticker), *[float(value) for value in row]])
    size = len(snapshot.tickers)
    _style_header(sheet, 1, size + 1)
    for row in range(2, size + 2):
        sheet.cell(row, 1).fill = SECTION_FILL
        sheet.cell(row, 1).font = Font(bold=True)
        for column in range(2, size + 2):
            sheet.cell(row, column).number_format = "0.000000"
    matrix_range = f"B2:{get_column_letter(size + 1)}{size + 1}"
    sheet.conditional_formatting.add(
        matrix_range,
        FormulaRule(
            formula=["COLUMN()-COLUMN($B$2)=ROW()-ROW($B$2)"],
            fill=DIAGONAL_FILL,
            stopIfTrue=True,
        ),
    )
    sheet.conditional_formatting.add(
        matrix_range,
        ColorScaleRule(
            start_type="num",
            start_value=-1,
            start_color="2166AC",
            mid_type="num",
            mid_value=0,
            mid_color="FFFFFF",
            end_type="num",
            end_value=1,
            end_color="B2182B",
        ),
    )
    sheet.freeze_panes = "B2"
    sheet.sheet_view.showGridLines = False
    sheet.column_dimensions["A"].width = 13
    for column in range(2, size + 2):
        sheet.column_dimensions[get_column_letter(column)].width = 10


def _write_exclusions(sheet: Worksheet, snapshot: PreprocessingSnapshot) -> None:
    sheet.append(["Market Cap Rank", "Ticker", "Reason"])
    for row in snapshot.exclusions.itertuples(index=False):
        sheet.append([int(row.market_cap_rank), str(row.ticker), str(row.reason)])
    _style_header(sheet, 1, 3)
    sheet.freeze_panes = "A2"
    sheet.sheet_view.showGridLines = False
    sheet.auto_filter.ref = f"A1:C{max(1, sheet.max_row)}"
    sheet.column_dimensions["A"].width = 18
    sheet.column_dimensions["B"].width = 14
    sheet.column_dimensions["C"].width = 48


def _style_header(sheet: Worksheet, row: int, columns: int) -> None:
    for column in range(1, columns + 1):
        cell = sheet.cell(row, column)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = Border(bottom=THIN_GRAY)
    sheet.row_dimensions[row].height = 24

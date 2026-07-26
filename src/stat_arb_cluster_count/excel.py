from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.worksheet.worksheet import Worksheet

from .models import ClusterCountResult


HEADER_FILL = PatternFill("solid", fgColor="1F4E78")
SECTION_FILL = PatternFill("solid", fgColor="D9EAF7")
OK_FILL = PatternFill("solid", fgColor="C6EFCE")
CHECK_FILL = PatternFill("solid", fgColor="FFC7CE")
HEADER_FONT = Font(color="FFFFFF", bold=True)
FORMULA_FONT = Font(color="008000")
THIN_GRAY = Side(style="thin", color="D9E2F3")
SCIENTIFIC_FORMAT = "0.000000000000E+00"
DECIMAL_FORMAT = "0.0000000000"


def export_cluster_count_workbook(
    result: ClusterCountResult,
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
    eigenvalues = workbook.create_sheet("Eigenvalues")
    calculation = workbook.create_sheet("K_Calculation")

    _write_eigenvalues(eigenvalues, result)
    _write_calculation(calculation, result)

    workbook.calculation.fullCalcOnLoad = True
    workbook.calculation.forceFullCalc = True
    workbook.save(output)
    return output


def _write_eigenvalues(sheet: Worksheet, result: ClusterCountResult) -> None:
    sheet.append(
        [
            "Rank",
            "Raw Eigenvalue",
            "Eigenvalue Used",
            "Numerical Adjustment",
        ]
    )
    for rank, (raw, effective) in enumerate(
        zip(result.raw_eigenvalues, result.effective_eigenvalues, strict=True),
        start=1,
    ):
        sheet.append([rank, raw, effective, effective - raw])

    _style_header(sheet, 1, 4)
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = f"A1:D{sheet.max_row}"
    sheet.sheet_view.showGridLines = False
    sheet.column_dimensions["A"].width = 10
    sheet.column_dimensions["B"].width = 24
    sheet.column_dimensions["C"].width = 24
    sheet.column_dimensions["D"].width = 24
    for row in range(2, sheet.max_row + 1):
        sheet.cell(row, 1).number_format = "0"
        for column in range(2, 5):
            sheet.cell(row, column).number_format = SCIENTIFIC_FORMAT


def _write_calculation(sheet: Worksheet, result: ClusterCountResult) -> None:
    rows = [
        ("Parameter / QC", "Program Value", "Excel Check", "Difference / Status"),
        ("As-of date", result.as_of_date, None, None),
        ("Cluster-count estimation window start", result.window_start, None, None),
        ("Cluster-count estimation window end", result.window_end, None, None),
        ("Preprocessing run id", result.preprocessing_run_id, None, None),
        ("Snapshot id (in-memory)", result.snapshot_id, None, None),
        ("Return basis", result.return_basis, None, None),
        ("Beta window", result.beta_window, None, None),
        (
            "Cluster-count estimation window",
            result.cluster_count_estimation_window,
            None,
            None,
        ),
        ("Source calculation version", result.source_calculation_version, None, None),
        ("Cluster-count version", result.calculation_version, None, None),
        ("Variance threshold P", result.variance_threshold, None, None),
        ("Stock count N", result.stock_count, None, None),
        ("Trace of C", result.quality.trace, None, None),
        ("Raw eigenvalue sum", result.quality.raw_eigenvalue_sum, None, None),
        ("Total variance used", result.total_variance, None, None),
        ("Minimum raw eigenvalue", result.quality.minimum_raw_eigenvalue, None, None),
        (
            "Adjusted negative eigenvalues",
            result.quality.adjusted_negative_eigenvalue_count,
            None,
            None,
        ),
        ("Numerical rank", result.quality.numerical_rank, None, None),
        ("Selected K", result.selected_k, None, None),
        ("Threshold crossing", "OK", None, None),
        ("Overall QC", "OK", None, None),
    ]
    for row in rows:
        sheet.append(row)

    table_header_row = len(rows) + 2
    first_detail_row = table_header_row + 1
    last_detail_row = first_detail_row + result.stock_count - 1
    eigenvalue_last_row = result.stock_count + 1

    sheet.cell(15, 3, f"=SUM('Eigenvalues'!B2:B{eigenvalue_last_row})")
    sheet.cell(15, 4, "=C15-B15")
    sheet.cell(16, 3, f"=SUM('Eigenvalues'!C2:C{eigenvalue_last_row})")
    sheet.cell(16, 4, "=C16-B16")
    sheet.cell(
        17,
        3,
        f"=MIN('Eigenvalues'!B2:B{eigenvalue_last_row})",
    )
    sheet.cell(17, 4, "=C17-B17")
    sheet.cell(
        18,
        3,
        f'=COUNTIF(\'Eigenvalues\'!D2:D{eigenvalue_last_row},">0")',
    )
    sheet.cell(18, 4, "=C18-B18")
    sheet.cell(
        19,
        3,
        f'=COUNTIF(\'Eigenvalues\'!C2:C{eigenvalue_last_row},">1E-10")',
    )
    sheet.cell(19, 4, "=C19-B19")
    sheet.cell(
        20,
        3,
        f'=COUNTIF(D{first_detail_row}:D{last_detail_row},"<"&B12)+1',
    )
    sheet.cell(20, 4, "=C20-B20")
    sheet.cell(
        21,
        3,
        (
            f'=IF(AND(INDEX(D{first_detail_row}:D{last_detail_row},B20)>=B12,'
            f'IF(B20=1,TRUE,INDEX(D{first_detail_row}:D{last_detail_row},B20-1)<B12)),'
            '"OK","CHECK")'
        ),
    )
    sheet.cell(21, 4, '=IF(C21=B21,"OK","CHECK")')
    sheet.cell(
        22,
        3,
        '=IF(AND(ABS(D15)<=1E-8,ABS(D16)<=1E-8,ABS(D17)<=1E-8,'
        'D18=0,D19=0,D20=0,D21="OK"),"OK","CHECK")',
    )
    sheet.cell(22, 4, '=IF(C22=B22,"OK","CHECK")')

    detail_headers = (
        "Rank",
        "Eigenvalue Used",
        "Cumulative Variance",
        "Cumulative Explained Ratio",
        "Threshold Reached",
        "Included in K",
    )
    for column, value in enumerate(detail_headers, start=1):
        sheet.cell(table_header_row, column, value)

    for rank in range(1, result.stock_count + 1):
        row = first_detail_row + rank - 1
        eigenvalue_row = rank + 1
        sheet.cell(row, 1, rank)
        sheet.cell(row, 2, f"='Eigenvalues'!C{eigenvalue_row}")
        sheet.cell(row, 3, f"=SUM($B${first_detail_row}:B{row})")
        sheet.cell(row, 4, f"=C{row}/$C$16")
        sheet.cell(row, 5, f'=IF(D{row}>=$B$12,"YES","NO")')
        sheet.cell(row, 6, f'=IF(A{row}<=$B$20,"YES","NO")')

    _style_header(sheet, 1, 4)
    _style_header(sheet, table_header_row, 6)
    for row in range(2, 23):
        sheet.cell(row, 1).fill = SECTION_FILL
        sheet.cell(row, 1).font = Font(bold=True)
    for row in (2, 3, 4):
        sheet.cell(row, 2).number_format = "yyyy-mm-dd"
    for row in (8, 9, 13, 18, 19, 20):
        sheet.cell(row, 2).number_format = "0"
        if sheet.cell(row, 3).value is not None:
            sheet.cell(row, 3).number_format = "0"
        if sheet.cell(row, 4).value is not None:
            sheet.cell(row, 4).number_format = "0"
    sheet.cell(12, 2).number_format = "0.00%"
    for row in (14, 15, 16):
        for column in (2, 3, 4):
            sheet.cell(row, column).number_format = DECIMAL_FORMAT
    for column in (2, 3, 4):
        sheet.cell(17, column).number_format = SCIENTIFIC_FORMAT
    for row in range(2, 23):
        for column in (3, 4):
            if isinstance(sheet.cell(row, column).value, str) and sheet.cell(
                row, column
            ).value.startswith("="):
                sheet.cell(row, column).font = FORMULA_FONT

    for row in range(first_detail_row, last_detail_row + 1):
        sheet.cell(row, 1).number_format = "0"
        sheet.cell(row, 2).number_format = SCIENTIFIC_FORMAT
        sheet.cell(row, 3).number_format = DECIMAL_FORMAT
        sheet.cell(row, 4).number_format = "0.0000%"
        for column in range(2, 7):
            sheet.cell(row, column).font = FORMULA_FONT

    for range_ref in ("C21:D22",):
        sheet.conditional_formatting.add(
            range_ref,
            CellIsRule(operator="equal", formula=['"OK"'], fill=OK_FILL),
        )
        sheet.conditional_formatting.add(
            range_ref,
            CellIsRule(operator="equal", formula=['"CHECK"'], fill=CHECK_FILL),
        )

    sheet.freeze_panes = f"A{first_detail_row}"
    sheet.auto_filter.ref = f"A{table_header_row}:F{last_detail_row}"
    sheet.sheet_view.showGridLines = False
    sheet.column_dimensions["A"].width = 36
    sheet.column_dimensions["B"].width = 28
    sheet.column_dimensions["C"].width = 24
    sheet.column_dimensions["D"].width = 24
    sheet.column_dimensions["E"].width = 20
    sheet.column_dimensions["F"].width = 16


def _style_header(sheet: Worksheet, row: int, columns: int) -> None:
    for column in range(1, columns + 1):
        cell = sheet.cell(row, column)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = Border(bottom=THIN_GRAY)
    sheet.row_dimensions[row].height = 24

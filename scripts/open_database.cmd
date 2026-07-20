@echo off
setlocal
set "PROJECT_DIR=%~dp0.."
set "PYTHON_EXE=%PROJECT_DIR%\.venv\Scripts\python.exe"
set "DATABASE_FILE=%PROJECT_DIR%\data\yahoo_market_data.duckdb"

if not exist "%PYTHON_EXE%" (
    echo Python environment not found: %PYTHON_EXE%
    echo Run the installation commands in README.md first.
    pause
    exit /b 1
)

if not exist "%DATABASE_FILE%" (
    echo Database not found: %DATABASE_FILE%
    echo Download the data first.
    pause
    exit /b 1
)

"%PYTHON_EXE%" -m stat_arb_data open --database "%DATABASE_FILE%"
if errorlevel 1 pause

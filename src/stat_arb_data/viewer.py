from __future__ import annotations

from pathlib import Path

import duckdb


def _connect_ui_catalog(database: Path) -> duckdb.DuckDBPyConnection:
    """Open writable UI storage with the requested database attached read-only."""

    ui_catalog = database.with_name(f"{database.stem}_ui.duckdb")
    database_literal = str(database).replace("'", "''")
    database_alias = database.stem.replace('"', '""')

    connection = duckdb.connect(str(ui_catalog))
    try:
        connection.execute(
            f"ATTACH '{database_literal}' AS \"{database_alias}\" (READ_ONLY)"
        )
    except BaseException:
        connection.close()
        raise
    return connection


def open_database_ui(database_path: Path) -> None:
    """Open a persistent DuckDB file in DuckDB's official local browser UI."""

    database = Path(database_path).resolve()
    if not database.exists():
        raise FileNotFoundError(
            f"Database does not exist: {database}\nRun scripts/run_data_download.py first."
        )

    # DuckDB's UI stores notebook state in its main catalog, so starting it
    # directly on a read-only database is unsupported. Keep the UI state in a
    # writable sidecar catalog and attach the market database read-only.
    connection = _connect_ui_catalog(database)
    try:
        try:
            connection.execute("LOAD ui")
        except duckdb.Error:
            connection.execute("INSTALL ui")
            connection.execute("LOAD ui")
        connection.execute("CALL start_ui()")
        print("DuckDB UI has started with the market database attached read-only.")
        print(
            "Press Enter in this terminal to stop the UI and release the database files."
        )
        input()
    except (KeyboardInterrupt, EOFError):
        return
    finally:
        connection.close()

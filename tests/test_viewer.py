from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import duckdb

from stat_arb_data.viewer import _connect_ui_catalog, open_database_ui


class DatabaseViewerTests(unittest.TestCase):
    def test_ui_uses_writable_catalog_and_attaches_market_database_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "market.duckdb"
            database.touch()
            connection = MagicMock()

            with (
                patch("stat_arb_data.viewer.duckdb.connect", return_value=connection) as connect,
                patch("builtins.input", return_value=""),
                patch("builtins.print"),
            ):
                open_database_ui(database)

            ui_catalog = database.with_name("market_ui.duckdb").resolve()
            connect.assert_called_once_with(str(ui_catalog))
            connection.execute.assert_any_call(
                f"ATTACH '{database.resolve()}' AS \"market\" (READ_ONLY)"
            )
            connection.execute.assert_any_call("LOAD ui")
            connection.execute.assert_any_call("CALL start_ui()")
            connection.close.assert_called_once_with()

    def test_ui_catalog_is_writable_and_market_database_stays_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = (Path(directory) / "market.duckdb").resolve()
            with duckdb.connect(str(database)) as setup:
                setup.execute("CREATE SCHEMA browse")
                setup.execute(
                    "CREATE VIEW browse.daily_quality AS SELECT 1 AS row_count"
                )

            connection = _connect_ui_catalog(database)
            try:
                result = connection.execute(
                    'SELECT * FROM "market".browse.daily_quality'
                ).fetchall()
                connection.execute("CREATE TABLE ui_write_probe(value INTEGER)")

                self.assertEqual(result, [(1,)])
                with self.assertRaisesRegex(duckdb.Error, "read-only mode"):
                    connection.execute(
                        'CREATE TABLE "market".main.must_not_write(value INTEGER)'
                    )
            finally:
                connection.close()

    def test_missing_database_is_rejected_before_opening_connection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "missing.duckdb"

            with (
                patch("stat_arb_data.viewer.duckdb.connect") as connect,
                self.assertRaises(FileNotFoundError),
            ):
                open_database_ui(database)

            connect.assert_not_called()


if __name__ == "__main__":
    unittest.main()

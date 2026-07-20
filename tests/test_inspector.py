from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import duckdb

from stat_arb_data.database import DuckDBInspector


class DuckDBInspectorTests(unittest.TestCase):
    def test_current_catalog_is_read_through_inspection_interface(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "current.duckdb"
            with duckdb.connect(str(database)) as connection:
                connection.execute(
                    """
                    CREATE SCHEMA market_data;
                    CREATE SCHEMA audit;
                    CREATE TABLE market_data.security_master (ticker VARCHAR);
                    CREATE TABLE audit.download_issues (
                        ticker VARCHAR,
                        stage VARCHAR,
                        issue VARCHAR,
                        recorded_at TIMESTAMPTZ
                    );
                    INSERT INTO market_data.security_master VALUES ('AAA');
                    """
                )

            with DuckDBInspector(database) as inspector:
                counts = dict(inspector.table_counts())
                issues = inspector.recent_download_issues()

            self.assertEqual(counts["market_data.security_master"], 1)
            self.assertTrue(issues.empty)

    def test_legacy_catalog_remains_inspectable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "legacy.duckdb"
            with duckdb.connect(str(database)) as connection:
                connection.execute(
                    """
                    CREATE SCHEMA raw;
                    CREATE SCHEMA quality;
                    CREATE TABLE raw.security_master (ticker VARCHAR);
                    CREATE TABLE quality.download_issues (
                        ticker VARCHAR,
                        stage VARCHAR,
                        issue VARCHAR,
                        recorded_at TIMESTAMPTZ
                    );
                    INSERT INTO raw.security_master VALUES ('AAA'), ('BBB');
                    """
                )

            with DuckDBInspector(database) as inspector:
                counts = dict(inspector.table_counts())

            self.assertEqual(counts["raw.security_master"], 2)


if __name__ == "__main__":
    unittest.main()

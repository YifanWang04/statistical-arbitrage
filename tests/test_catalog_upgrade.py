from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

import duckdb

from stat_arb_data.application import upgrade_database_catalog
from stat_arb_data.config import PipelineConfig
from stat_arb_data.database import DuckDBInspector
from stat_arb_data.pipeline import DataPipeline
from tests.test_pipeline import FakeSource


class CatalogUpgradeTests(unittest.TestCase):
    def test_legacy_database_is_upgraded_without_redownloading_data(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            current_source = root / "current-source.duckdb"
            legacy = root / "legacy.duckdb"
            config = PipelineConfig(
                database_path=current_source,
                start_date=date(2020, 1, 1),
                end_date=date(2020, 1, 6),
                top_n=1,
            )
            DataPipeline(config, source=FakeSource()).run()
            self._create_legacy_copy(current_source, legacy)

            upgraded = upgrade_database_catalog(legacy)

            self.assertTrue(upgraded)
            with DuckDBInspector(legacy) as inspector:
                self.assertEqual(inspector.catalog_version, "current")
                counts = dict(inspector.table_counts())
            self.assertEqual(counts["market_data.security_master"], 2)
            self.assertEqual(counts["market_data.universe_membership"], 2)

            with duckdb.connect(str(legacy), read_only=True) as connection:
                custom_schemas = connection.execute(
                    """
                    SELECT schema_name
                    FROM information_schema.schemata
                    WHERE schema_name IN (
                        'market_data', 'audit', 'browse',
                        'meta', 'raw', 'core', 'quality'
                    )
                    ORDER BY schema_name
                    """
                ).fetchall()
                browse_views = connection.execute(
                    """
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = 'browse'
                    ORDER BY table_name
                    """
                ).fetchall()
                beta_setting = connection.execute(
                    """
                    SELECT COUNT(*) FROM audit.settings
                    WHERE setting_key = 'beta_window'
                    """
                ).fetchone()[0]

            self.assertEqual(
                custom_schemas,
                [("audit",), ("browse",), ("market_data",)],
            )
            self.assertEqual(
                browse_views,
                [("daily_quality",), ("daily_universe",), ("latest_universe",)],
            )
            self.assertEqual(beta_setting, 0)

    def test_current_catalog_upgrade_is_a_no_op(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "current.duckdb"
            with duckdb.connect(str(database)) as connection:
                connection.execute("CREATE SCHEMA market_data; CREATE SCHEMA audit;")

            self.assertFalse(upgrade_database_catalog(database))

    @staticmethod
    def _create_legacy_copy(current: Path, legacy: Path) -> None:
        escaped = str(current.resolve()).replace("'", "''")
        with duckdb.connect(str(legacy)) as connection:
            connection.execute(f"ATTACH '{escaped}' AS source (READ_ONLY)")
            connection.execute(
                """
                CREATE SCHEMA meta;
                CREATE SCHEMA raw;
                CREATE SCHEMA core;
                CREATE SCHEMA quality;
                CREATE SCHEMA browse;

                CREATE TABLE meta.pipeline_runs AS
                    SELECT * FROM source.audit.pipeline_runs;
                CREATE TABLE meta.settings AS
                    SELECT * FROM source.audit.settings;
                INSERT INTO meta.settings
                    VALUES ('beta_window', '60', 'legacy future-stage setting');
                CREATE TABLE meta.data_dictionary AS
                    SELECT * FROM source.audit.data_dictionary;
                CREATE TABLE raw.security_master AS
                    SELECT * FROM source.market_data.security_master;
                CREATE TABLE raw.daily_prices AS
                    SELECT * FROM source.market_data.daily_prices;
                CREATE TABLE raw.shares_outstanding AS
                    SELECT * FROM source.market_data.shares_outstanding;
                CREATE TABLE core.market_returns AS
                    SELECT * FROM source.market_data.market_returns;
                CREATE TABLE core.daily_market_cap AS
                    SELECT * FROM source.market_data.daily_market_cap;
                CREATE TABLE core.universe_membership AS
                    SELECT * FROM source.market_data.universe_membership;
                CREATE TABLE quality.download_issues AS
                    SELECT * FROM source.audit.download_issues;
                """
            )
            connection.execute("DETACH source")


if __name__ == "__main__":
    unittest.main()

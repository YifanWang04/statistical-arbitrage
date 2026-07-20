from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from stat_arb_data.application import build_database
from stat_arb_data.config import PipelineConfig


class _SuccessfulPipeline:
    def __init__(self, config: PipelineConfig) -> None:
        self.config = config

    def run(self) -> str:
        self.config.database_path.write_bytes(b"new database")
        return "successful-run"


class _FailingPipeline:
    def __init__(self, config: PipelineConfig) -> None:
        self.config = config

    def run(self) -> str:
        self.config.database_path.write_bytes(b"partial database")
        raise RuntimeError("download failed")


class DatabaseBuildTests(unittest.TestCase):
    def test_first_build_publishes_without_replace_permission(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "market.duckdb"
            config = PipelineConfig(database_path=database)

            with patch("stat_arb_data.application.DataPipeline", _SuccessfulPipeline):
                run_id = build_database(config)

            self.assertEqual(run_id, "successful-run")
            self.assertEqual(database.read_bytes(), b"new database")

    def test_existing_database_is_not_replaced_without_explicit_permission(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "market.duckdb"
            database.write_bytes(b"existing database")
            config = PipelineConfig(database_path=database)

            with self.assertRaises(FileExistsError):
                build_database(config, replace_existing=False)

            self.assertEqual(database.read_bytes(), b"existing database")

    def test_failed_rebuild_preserves_existing_database_and_removes_partial_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "market.duckdb"
            database.write_bytes(b"existing database")
            config = PipelineConfig(database_path=database)

            with patch("stat_arb_data.application.DataPipeline", _FailingPipeline):
                with self.assertRaisesRegex(RuntimeError, "download failed"):
                    build_database(config, replace_existing=True)

            self.assertEqual(database.read_bytes(), b"existing database")
            self.assertEqual(list(database.parent.glob("*.tmp")), [])

    def test_successful_rebuild_publishes_complete_database(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "market.duckdb"
            database.write_bytes(b"existing database")
            config = PipelineConfig(database_path=database)

            with patch("stat_arb_data.application.DataPipeline", _SuccessfulPipeline):
                run_id = build_database(config, replace_existing=True)

            self.assertEqual(run_id, "successful-run")
            self.assertEqual(database.read_bytes(), b"new database")
            self.assertEqual(list(database.parent.glob("*.tmp")), [])

    def test_existing_wal_blocks_rebuild_without_touching_database(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "market.duckdb"
            database.write_bytes(b"existing database")
            Path(f"{database}.wal").write_bytes(b"uncheckpointed changes")
            config = PipelineConfig(database_path=database)

            with self.assertRaisesRegex(RuntimeError, "WAL exists"):
                build_database(config, replace_existing=True)

            self.assertEqual(database.read_bytes(), b"existing database")


if __name__ == "__main__":
    unittest.main()

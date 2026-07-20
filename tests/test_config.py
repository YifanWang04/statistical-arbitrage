from __future__ import annotations

import unittest
from datetime import date
from pathlib import Path

from stat_arb_data.config import PipelineConfig, default_end_date


class PipelineConfigTests(unittest.TestCase):
    def test_default_end_is_previous_calendar_date(self) -> None:
        self.assertEqual(default_end_date(date(2026, 7, 17)), date(2026, 7, 16))

    def test_rejects_invalid_range(self) -> None:
        with self.assertRaises(ValueError):
            PipelineConfig(
                database_path=Path("test.duckdb"),
                start_date=date(2020, 1, 1),
                end_date=date(2020, 1, 1),
            )

    def test_candidate_pool_cannot_be_smaller_than_daily_selection(self) -> None:
        with self.assertRaises(ValueError):
            PipelineConfig(
                database_path=Path("test.duckdb"),
                start_date=date(2020, 1, 1),
                end_date=date(2020, 2, 1),
                top_n=500,
                candidate_pool_size=499,
            )


if __name__ == "__main__":
    unittest.main()

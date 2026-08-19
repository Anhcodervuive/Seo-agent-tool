import datetime
import unittest
from types import SimpleNamespace

from app.models import Snapshot
from services.project_history import _encode_cursor, _parse_cursor


class ProjectHistoryCursorTests(unittest.TestCase):
    def test_cursor_round_trip_keeps_timestamp_and_snapshot_id(self):
        snapshot = SimpleNamespace(id=42, created_at=datetime.datetime(2026, 8, 19, 10, 30, 15))
        self.assertEqual((snapshot.created_at, 42), _parse_cursor(_encode_cursor(snapshot)))

    def test_invalid_cursor_is_ignored(self):
        self.assertIsNone(_parse_cursor("invalid"))
        self.assertIsNone(_parse_cursor("2026-08-19T10:30:00|not-a-number"))

    def test_snapshot_model_declares_cursor_query_index(self):
        indexes = {index.name: tuple(column.name for column in index.columns) for index in Snapshot.__table__.indexes}
        self.assertEqual(
            ("client_id", "created_at", "id"),
            indexes["ix_snapshots_client_created_id"],
        )


if __name__ == "__main__":
    unittest.main()

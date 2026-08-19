import datetime
import unittest

from services.audit_queue import next_scheduled_time, retry_backoff_minutes


class AuditQueueHelperTests(unittest.TestCase):
    def test_retry_backoff_is_exponential(self):
        self.assertEqual(retry_backoff_minutes(0, 5), 5)
        self.assertEqual(retry_backoff_minutes(1, 5), 10)
        self.assertEqual(retry_backoff_minutes(2, 5), 20)

    def test_daily_schedule_preserves_local_wall_clock(self):
        current = datetime.datetime(2026, 8, 19, 10, 0)
        next_run = next_scheduled_time(current, "daily", "Asia/Kolkata", "02:00")
        self.assertEqual(next_run, datetime.datetime(2026, 8, 19, 20, 30))

    def test_monthly_schedule_clamps_end_of_month(self):
        current = datetime.datetime(2026, 1, 31, 23, 0)
        next_run = next_scheduled_time(current, "monthly", "Asia/Kolkata", "02:00")
        self.assertEqual(next_run, datetime.datetime(2026, 2, 28, 20, 30))


if __name__ == "__main__":
    unittest.main()

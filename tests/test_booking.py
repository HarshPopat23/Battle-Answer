"""Regression tests for find_conflicts in booking.py using unittest."""

import unittest
from booking import find_conflicts


class TestBookingConflicts(unittest.TestCase):
    def test_required_scenario(self):
        """
        A: 2026-10-20T10:00:00+05:30 to 2026-10-20T11:00:00+05:30 (04:30Z - 05:30Z)
        B: 2026-10-20T05:00:00Z to 2026-10-20T06:00:00Z
        C: 2026-10-20T06:00:00Z to 2026-10-20T07:00:00Z
        """
        bookings = [
            {"id": "A", "start": "2026-10-20T10:00:00+05:30", "end": "2026-10-20T11:00:00+05:30"},
            {"id": "B", "start": "2026-10-20T05:00:00Z", "end": "2026-10-20T06:00:00Z"},
            {"id": "C", "start": "2026-10-20T06:00:00Z", "end": "2026-10-20T07:00:00Z"},
        ]
        result = find_conflicts(bookings)
        self.assertEqual(result, [("A", "B")])

    def test_adjacent_intervals_do_not_overlap(self):
        bookings = [
            {"id": "1", "start": "2026-01-01T10:00:00Z", "end": "2026-01-01T11:00:00Z"},
            {"id": "2", "start": "2026-01-01T11:00:00Z", "end": "2026-01-01T12:00:00Z"},
        ]
        self.assertEqual(find_conflicts(bookings), [])

    def test_multiple_conflicts_sorted(self):
        bookings = [
            {"id": "Z", "start": "2026-01-01T10:00:00Z", "end": "2026-01-01T12:00:00Z"},
            {"id": "A", "start": "2026-01-01T11:00:00Z", "end": "2026-01-01T13:00:00Z"},
            {"id": "M", "start": "2026-01-01T11:30:00Z", "end": "2026-01-01T14:00:00Z"},
        ]
        self.assertEqual(find_conflicts(bookings), [("A", "M"), ("A", "Z"), ("M", "Z")])

    def test_reject_naive_timestamp_missing_timezone(self):
        with self.assertRaises(ValueError):
            find_conflicts([
                {"id": "1", "start": "2026-10-20T10:00:00", "end": "2026-10-20T11:00:00Z"}
            ])
        with self.assertRaises(ValueError):
            find_conflicts([
                {"id": "1", "start": "2026-10-20T10:00:00Z", "end": "2026-10-20T11:00:00"}
            ])

    def test_reject_duplicate_ids(self):
        with self.assertRaises(ValueError):
            find_conflicts([
                {"id": "dup", "start": "2026-10-20T10:00:00Z", "end": "2026-10-20T11:00:00Z"},
                {"id": "dup", "start": "2026-10-20T12:00:00Z", "end": "2026-10-20T13:00:00Z"},
            ])

    def test_reject_end_less_than_or_equal_to_start(self):
        with self.assertRaises(ValueError):
            find_conflicts([
                {"id": "equal", "start": "2026-10-20T10:00:00Z", "end": "2026-10-20T10:00:00Z"}
            ])
        with self.assertRaises(ValueError):
            find_conflicts([
                {"id": "reversed", "start": "2026-10-20T11:00:00Z", "end": "2026-10-20T10:00:00Z"}
            ])

    def test_does_not_modify_input(self):
        original = [
            {"id": "B", "start": "2026-10-20T05:00:00Z", "end": "2026-10-20T06:00:00Z"},
            {"id": "A", "start": "2026-10-20T10:00:00+05:30", "end": "2026-10-20T11:00:00+05:30"},
        ]
        original_copy = [dict(x) for x in original]
        find_conflicts(original)
        self.assertEqual(original, original_copy)


if __name__ == "__main__":
    unittest.main()

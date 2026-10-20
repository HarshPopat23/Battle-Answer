import unittest

from booking import find_conflicts


class BookingConflictTest(unittest.TestCase):
    def test_example_cross_timezone_conflict(self):
        bookings = [
            {"id": "A", "start": "2026-10-20T10:00:00+05:30", "end": "2026-10-20T11:00:00+05:30"},
            {"id": "B", "start": "2026-10-20T05:00:00Z", "end": "2026-10-20T06:00:00Z"},
            {"id": "C", "start": "2026-10-20T06:00:00Z", "end": "2026-10-20T07:00:00Z"},
        ]
        # A = 04:30Z-05:30Z. B and C are adjacent. Only A overlaps B.
        self.assertEqual(find_conflicts(bookings), [["A", "B"]])

    def test_adjacent_non_overlapping(self):
        bookings = [
            {"id": "x", "start": "2026-01-01T10:00:00+00:00", "end": "2026-01-01T11:00:00+00:00"},
            {"id": "y", "start": "2026-01-01T11:00:00+00:00", "end": "2026-01-01T12:00:00+00:00"},
        ]
        self.assertEqual(find_conflicts(bookings), [])

    def test_empty_input(self):
        self.assertEqual(find_conflicts([]), [])

    def test_duplicate_ids_rejected(self):
        bookings = [
            {"id": "a", "start": "2026-01-01T00:00:00Z", "end": "2026-01-01T01:00:00Z"},
            {"id": "a", "start": "2026-01-01T02:00:00Z", "end": "2026-01-01T03:00:00Z"},
        ]
        with self.assertRaises(ValueError):
            find_conflicts(bookings)

    def test_missing_timezone_rejected(self):
        bookings = [
            {"id": "a", "start": "2026-01-01T00:00:00", "end": "2026-01-01T01:00:00"},
        ]
        with self.assertRaises(ValueError):
            find_conflicts(bookings)

    def test_malformed_timestamp_rejected(self):
        bookings = [
            {"id": "a", "start": "not-a-time", "end": "2026-01-01T01:00:00Z"},
        ]
        with self.assertRaises(ValueError):
            find_conflicts(bookings)

    def test_empty_id_rejected(self):
        bookings = [
            {"id": "", "start": "2026-01-01T00:00:00Z", "end": "2026-01-01T01:00:00Z"},
        ]
        with self.assertRaises(ValueError):
            find_conflicts(bookings)

    def test_end_before_start_rejected(self):
        bookings = [
            {"id": "a", "start": "2026-01-01T01:00:00Z", "end": "2026-01-01T00:00:00Z"},
        ]
        with self.assertRaises(ValueError):
            find_conflicts(bookings)

    def test_end_equal_start_rejected(self):
        bookings = [
            {"id": "a", "start": "2026-01-01T01:00:00Z", "end": "2026-01-01T01:00:00Z"},
        ]
        with self.assertRaises(ValueError):
            find_conflicts(bookings)

    def test_spans_midnight_conflict(self):
        bookings = [
            {"id": "night", "start": "2026-11-20T23:00:00Z", "end": "2026-11-21T01:00:00Z"},
            {"id": "early", "start": "2026-11-21T00:30:00Z", "end": "2026-11-21T00:45:00Z"},
        ]
        self.assertEqual(find_conflicts(bookings), [["early", "night"]])

    def test_does_not_modify_input(self):
        original = [
            {"id": "a", "start": "2026-01-01T00:00:00Z", "end": "2026-01-01T01:00:00Z"},
            {"id": "b", "start": "2026-01-01T00:30:00Z", "end": "2026-01-01T02:00:00Z"},
        ]
        copy = [
            {"id": item["id"], "start": item["start"], "end": item["end"]}
            for item in original
        ]
        self.assertEqual(find_conflicts(original), [["a", "b"]])
        self.assertEqual(original, copy)

    def test_pair_sorted_alphabetically_and_no_duplicates(self):
        bookings = [
            {"id": "zeta", "start": "2026-01-01T00:00:00Z", "end": "2026-01-01T02:00:00Z"},
            {"id": "alpha", "start": "2026-01-01T01:00:00Z", "end": "2026-01-01T03:00:00Z"},
            {"id": "mid", "start": "2026-01-01T01:30:00Z", "end": "2026-01-01T02:30:00Z"},
        ]
        self.assertEqual(find_conflicts(bookings), [["alpha", "mid"], ["alpha", "zeta"], ["mid", "zeta"]])


if __name__ == "__main__":
    unittest.main()

"""Booking conflict finder comparing exact instants across timezones."""

from datetime import datetime
from typing import Any, Dict, List, Tuple


def find_conflicts(bookings: List[Dict[str, Any]]) -> List[Tuple[str, str]]:
    """
    Find all overlapping pairs of booking intervals across arbitrary timezones.

    Rules:
    - Intervals are half-open: [start, end). Adjacent bookings do not overlap.
    - Rejects missing timezones, duplicate IDs, and end <= start with ValueError.
    - Does not modify input.
    - Each returned pair is sorted alphabetically: (id1, id2) where id1 < id2.
    - Full list of pairs is sorted lexicographically.
    """
    if not isinstance(bookings, list):
        raise TypeError("bookings must be a list of dictionaries")

    seen_ids = set()
    normalized = []

    for item in bookings:
        if not isinstance(item, dict):
            raise TypeError("Each booking must be a dictionary")

        if "id" not in item:
            raise ValueError("Booking missing 'id' key")
        bid = str(item["id"])
        if not bid or bid in seen_ids:
            raise ValueError(f"Invalid or duplicate booking ID: {bid!r}")
        seen_ids.add(bid)

        if "start" not in item or "end" not in item:
            raise ValueError(f"Booking {bid} missing 'start' or 'end' timestamp")

        s_raw, e_raw = item["start"], item["end"]
        if not isinstance(s_raw, str) or not isinstance(e_raw, str):
            raise TypeError(f"Timestamps must be ISO 8601 strings for booking {bid}")

        try:
            start_dt = datetime.fromisoformat(s_raw)
        except Exception as exc:
            raise ValueError(f"Malformed start timestamp in booking {bid}: {s_raw}") from exc

        try:
            end_dt = datetime.fromisoformat(e_raw)
        except Exception as exc:
            raise ValueError(f"Malformed end timestamp in booking {bid}: {e_raw}") from exc

        # Strict requirement: Reject missing timezones (naive datetime)
        if start_dt.tzinfo is None:
            raise ValueError(f"Booking {bid} start timestamp is naive (missing timezone): {s_raw}")
        if end_dt.tzinfo is None:
            raise ValueError(f"Booking {bid} end timestamp is naive (missing timezone): {e_raw}")

        # Strict requirement: Reject end <= start
        if end_dt <= start_dt:
            raise ValueError(f"Booking {bid} has invalid duration (end <= start): {s_raw} -> {e_raw}")

        normalized.append((bid, start_dt, end_dt))

    # Interval intersection check: [s1, e1) and [s2, e2) overlap iff max(s1, s2) < min(e1, e2)
    conflicts = set()
    total = len(normalized)
    for i in range(total):
        id1, s1, e1 = normalized[i]
        for j in range(i + 1, total):
            id2, s2, e2 = normalized[j]
            if max(s1, s2) < min(e1, e2):
                pair = (id1, id2) if id1 < id2 else (id2, id1)
                conflicts.add(pair)

    return sorted(list(conflicts))

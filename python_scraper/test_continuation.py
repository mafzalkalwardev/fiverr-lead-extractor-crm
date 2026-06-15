"""Tests for job queue continuation helpers."""
from __future__ import annotations

import unittest


def unprocessed_tail(queue: list[str], resume_index: int) -> list[str]:
    idx = max(0, min(resume_index, len(queue)))
    return queue[idx:]


class TestUnprocessedTail(unittest.TestCase):
    def test_returns_remaining_gigs(self):
        queue = [f"https://www.fiverr.com/u{i}/gig" for i in range(500)]
        tail = unprocessed_tail(queue, 200)
        self.assertEqual(len(tail), 300)
        self.assertEqual(tail[0], queue[200])

    def test_empty_when_fully_processed(self):
        queue = ["https://www.fiverr.com/a/gig", "https://www.fiverr.com/b/gig"]
        self.assertEqual(unprocessed_tail(queue, 2), [])


if __name__ == "__main__":
    unittest.main()

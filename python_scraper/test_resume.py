"""Unit tests for job resume / lead-limit checkpoint behavior."""
from __future__ import annotations

import unittest


def processed_urls_from_job(doc: dict) -> list[str]:
    """Mirror of db.previous_gig_urls_for_niche queue slicing (test helper)."""
    queue = list(doc.get("gigQueue") or doc.get("manualGigUrls") or [])
    if not queue:
        return []
    resume_idx = int(doc.get("resumeIndex") or 0)
    status = doc.get("status") or ""
    if status == "completed" and resume_idx >= len(queue):
        return queue
    return queue[: max(0, min(resume_idx, len(queue)))]


def should_pause_for_lead_limit(
    stopped_reason: str | None, resume_index: int, queue_len: int
) -> bool:
    remaining = max(0, queue_len - resume_index)
    return stopped_reason == "lead_limit" and remaining > 0


class TestProcessedUrlExclusion(unittest.TestCase):
    def test_partial_job_excludes_only_processed_slice(self):
        doc = {
            "status": "lead_limit_reached",
            "resumeIndex": 200,
            "gigQueue": [f"https://www.fiverr.com/u{i}/gig" for i in range(500)],
        }
        processed = processed_urls_from_job(doc)
        self.assertEqual(len(processed), 200)
        self.assertEqual(processed[0], doc["gigQueue"][0])
        self.assertEqual(processed[-1], doc["gigQueue"][199])

    def test_completed_job_excludes_full_queue(self):
        doc = {
            "status": "completed",
            "resumeIndex": 500,
            "gigQueue": [f"https://www.fiverr.com/u{i}/gig" for i in range(500)],
        }
        processed = processed_urls_from_job(doc)
        self.assertEqual(len(processed), 500)

    def test_legacy_completed_with_partial_index_excludes_partial(self):
        """Backward compat: old jobs marked completed at lead limit."""
        doc = {
            "status": "completed",
            "resumeIndex": 200,
            "gigQueue": [f"https://www.fiverr.com/u{i}/gig" for i in range(500)],
        }
        processed = processed_urls_from_job(doc)
        self.assertEqual(len(processed), 200)


class TestLeadLimitPause(unittest.TestCase):
    def test_pauses_when_limit_hit_with_remaining_gigs(self):
        self.assertTrue(should_pause_for_lead_limit("lead_limit", 200, 500))

    def test_completes_when_all_gigs_processed(self):
        self.assertFalse(should_pause_for_lead_limit("lead_limit", 500, 500))

    def test_completes_when_no_lead_limit_stop(self):
        self.assertFalse(should_pause_for_lead_limit(None, 200, 500))


if __name__ == "__main__":
    unittest.main()

import unittest
import tempfile
from pathlib import Path

from performance_utils import (
    MemoryCache,
    bounded_worker_count,
    is_complete_file,
    prefetch_stream_infos,
    run_limited_concurrent,
)


class MemoryCacheTests(unittest.TestCase):
    def test_cache_tracks_presence_separately_from_value_truthiness(self):
        cache = MemoryCache()

        cache.set("empty-list", [])

        self.assertTrue(cache.has("empty-list"))
        self.assertEqual(cache.get("empty-list"), [])
        self.assertFalse(cache.has("missing"))


class StreamPrefetchTests(unittest.TestCase):
    def test_prefetch_preserves_result_by_item_index(self):
        class FakeCrawler:
            def get_stream_info(self, sched_id, user_level=1, user_id=""):
                return {"sched_id": sched_id, "user_id": user_id}

        items = [{"sched_id": "a"}, {"sched_id": "b"}]

        results = prefetch_stream_infos(FakeCrawler, items, "u1", max_workers=2)

        self.assertEqual(results[0], {"sched_id": "a", "user_id": "u1"})
        self.assertEqual(results[1], {"sched_id": "b", "user_id": "u1"})

    def test_bounded_worker_count_caps_to_total_and_upper_bound(self):
        self.assertEqual(bounded_worker_count(99, total=3, upper=5), 3)
        self.assertEqual(bounded_worker_count("bad", total=10, default=4), 4)

    def test_limited_concurrent_returns_results_in_input_order(self):
        items = ["a", "b", "c"]

        results = run_limited_concurrent(
            items,
            lambda idx, item: f"{idx}:{item}",
            max_workers=2,
        )

        self.assertEqual(results, ["0:a", "1:b", "2:c"])


class FileCompletionTests(unittest.TestCase):
    def test_complete_file_requires_existing_file_above_threshold(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "lesson.m4a"
            path.write_bytes(b"12345")

            self.assertTrue(is_complete_file(str(path), min_bytes=5))
            self.assertFalse(is_complete_file(str(path), min_bytes=6))
            self.assertFalse(is_complete_file(str(path.with_suffix(".missing"))))


if __name__ == "__main__":
    unittest.main()

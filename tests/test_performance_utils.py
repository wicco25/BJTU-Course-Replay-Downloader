import unittest
import tempfile
from pathlib import Path

from performance_utils import (
    MemoryCache,
    ProgressThrottler,
    build_download_stream_index,
    build_download_time_index,
    bounded_worker_count,
    extract_download_identity,
    extract_download_stream_key,
    extract_download_time_key,
    is_audio_file,
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


class ProgressThrottlerTests(unittest.TestCase):
    def test_throttler_emits_first_and_suppresses_tiny_updates(self):
        current = [0.0]
        throttler = ProgressThrottler(
            min_interval=1.0,
            min_delta=0.1,
            clock=lambda: current[0],
        )

        self.assertTrue(throttler.should_emit(0.0))
        current[0] = 2.0
        self.assertFalse(throttler.should_emit(0.05))
        self.assertTrue(throttler.should_emit(0.2))

    def test_throttler_always_emits_completion(self):
        throttler = ProgressThrottler(min_interval=999, min_delta=999)

        self.assertTrue(throttler.should_emit(0.0))
        self.assertTrue(throttler.should_emit(1.0))


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

    def test_audio_file_detection_is_extension_based(self):
        self.assertTrue(is_audio_file("lesson.M4A"))
        self.assertTrue(is_audio_file("lecture.mp3"))
        self.assertFalse(is_audio_file("lecture.mp4"))

    def test_download_time_index_extracts_course_time_keys(self):
        filenames = [
            "微积分_2026-04-29_1010-1200_课件画面.m4a",
            "bad-name.m4a",
            "英语_2026-04-30_0800-0950_课件画面.mp3",
        ]

        self.assertEqual(
            extract_download_time_key(filenames[0]),
            "2026-04-29_1010-1200",
        )
        self.assertEqual(
            build_download_time_index(filenames),
            {"2026-04-29_1010-1200", "2026-04-30_0800-0950"},
        )

    def test_download_stream_index_distinguishes_urls_for_same_replay(self):
        stream_labels = {
            "course_url": "课件画面",
            "teacher_url": "教师画面",
            "student_url": "学生画面",
        }
        filenames = [
            "数学_2026-04-29_1010-1200_课件画面_视频.mp4",
            "数学_2026-04-29_1010-1200_教师画面_视频.mp4",
            "数学_2026-04-29_1010-1200_学生画面_音频.m4a",
            "数学_2026-04-29_1010-1200_教师特写_视频.mp4",
        ]

        self.assertEqual(
            extract_download_stream_key(filenames[0], stream_labels),
            "course_url",
        )
        self.assertEqual(
            extract_download_identity(filenames[1], stream_labels),
            ("2026-04-29_1010-1200", "teacher_url"),
        )
        self.assertEqual(
            build_download_stream_index(filenames, stream_labels),
            {
                ("2026-04-29_1010-1200", "course_url"),
                ("2026-04-29_1010-1200", "teacher_url"),
                ("2026-04-29_1010-1200", "student_url"),
            },
        )


if __name__ == "__main__":
    unittest.main()

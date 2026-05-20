"""Small runtime helpers for keeping UI/network work lean."""

import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed


class MemoryCache:
    """Tiny explicit cache used by the GUI to avoid repeat API calls."""

    def __init__(self):
        self._values = {}

    def get(self, key, default=None):
        return self._values.get(key, default)

    def set(self, key, value):
        self._values[key] = value
        return value

    def has(self, key):
        return key in self._values

    def clear(self):
        self._values.clear()


class ProgressThrottler:
    """Decide when a progress update is worth emitting to the UI."""

    def __init__(self, min_interval=0.3, min_delta=0.01, clock=None):
        self.min_interval = min_interval
        self.min_delta = min_delta
        self.clock = clock or time.monotonic
        self._last_time = None
        self._last_value = None

    def should_emit(self, value, force=False):
        if force:
            self._remember(value)
            return True
        now = self.clock()
        if self._last_value is None:
            self._last_time = now
            self._last_value = value
            return True
        if value >= 1.0:
            self._remember(value, now)
            return True
        if value - self._last_value < self.min_delta:
            return False
        if now - self._last_time < self.min_interval:
            return False
        self._remember(value, now)
        return True

    def _remember(self, value, now=None):
        self._last_time = self.clock() if now is None else now
        self._last_value = value


def bounded_worker_count(requested, total, default=4, lower=1, upper=5):
    try:
        count = int(requested)
    except (TypeError, ValueError):
        count = default
    count = max(lower, min(upper, count))
    return max(lower, min(count, max(total, lower)))


def prefetch_stream_infos(crawler_factory, items, user_id, max_workers=4):
    """Fetch stream info ahead of downloads without changing crawler semantics."""
    total = len(items)
    if total == 0:
        return {}

    workers = bounded_worker_count(max_workers, total)
    if workers <= 1:
        crawler = crawler_factory()
        return {
            idx: crawler.get_stream_info(
                item["sched_id"], user_level=1, user_id=user_id
            )
            for idx, item in enumerate(items)
        }

    results = {}
    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_map = {
            executor.submit(
                crawler_factory().get_stream_info,
                item["sched_id"],
                user_level=1,
                user_id=user_id,
            ): idx
            for idx, item in enumerate(items)
        }
        for future in as_completed(future_map):
            idx = future_map[future]
            try:
                results[idx] = future.result()
            except Exception:
                results[idx] = None
    return results


def run_limited_concurrent(items, worker, max_workers=2, upper=3):
    """Run item work with bounded concurrency and return results by item order."""
    total = len(items)
    if total == 0:
        return []

    workers = bounded_worker_count(max_workers, total, default=2, upper=upper)
    if workers <= 1:
        return [worker(idx, item) for idx, item in enumerate(items)]

    results = [None] * total
    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_map = {
            executor.submit(worker, idx, item): idx
            for idx, item in enumerate(items)
        }
        for future in as_completed(future_map):
            idx = future_map[future]
            results[idx] = future.result()
    return results


def is_complete_file(path, min_bytes=1024 * 1024):
    """Treat an existing non-trivial media file as already downloaded."""
    try:
        return bool(path) and os.path.isfile(path) and os.path.getsize(path) >= min_bytes
    except OSError:
        return False


def is_audio_file(path):
    return str(path).lower().endswith((".mp3", ".wav", ".m4a", ".flac", ".aac"))


DOWNLOAD_TIME_RE = re.compile(r"\d{4}-\d{2}-\d{2}_\d{4}-\d{4}")


def extract_download_time_key(filename):
    match = DOWNLOAD_TIME_RE.search(str(filename))
    return match.group(0) if match else ""


def build_download_time_index(filenames):
    return {
        key
        for key in (extract_download_time_key(filename) for filename in filenames)
        if key
    }


def extract_download_stream_key(filename, stream_labels):
    """Return the stream key encoded in a generated download filename."""
    text = str(filename)
    for stream_key, label in stream_labels.items():
        if f"_{label}_" in text:
            return stream_key
    return ""


def extract_download_identity(filename, stream_labels):
    time_key = extract_download_time_key(filename)
    stream_key = extract_download_stream_key(filename, stream_labels)
    if not time_key or not stream_key:
        return None
    return time_key, stream_key


def build_download_stream_index(filenames, stream_labels):
    return {
        identity
        for identity in (
            extract_download_identity(filename, stream_labels)
            for filename in filenames
        )
        if identity
    }

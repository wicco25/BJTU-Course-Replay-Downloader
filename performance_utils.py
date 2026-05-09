"""Small runtime helpers for keeping UI/network work lean."""

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

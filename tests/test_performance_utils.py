import unittest

from performance_utils import MemoryCache


class MemoryCacheTests(unittest.TestCase):
    def test_cache_tracks_presence_separately_from_value_truthiness(self):
        cache = MemoryCache()

        cache.set("empty-list", [])

        self.assertTrue(cache.has("empty-list"))
        self.assertEqual(cache.get("empty-list"), [])
        self.assertFalse(cache.has("missing"))


if __name__ == "__main__":
    unittest.main()

"""Small runtime helpers for keeping UI/network work lean."""


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

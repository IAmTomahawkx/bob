import time

class ExpiringDict(dict):
    def __init__(self, *, timeout=30):
        self._timeout = timeout
        super().__init__()

    def __getitem__(self, item):
        self._remove_old_keys()
        return super().__getitem__(item)[1]

    def __setitem__(self, key, value):
        self._remove_old_keys()
        super().__setitem__(key, (time.monotonic(), value))

    def pop(self, key):
        self._remove_old_keys()
        return super().pop(key)[1]

    def maybe_pop(self, key, default=None):
        try:
            return self.pop(key)
        except KeyError:
            return default

    def get(self, key, default=None):
        self._remove_old_keys()
        v = super().get(key)
        if v is None:
            return default

        return v[1]

    def _remove_old_keys(self):
        now = time.monotonic()
        for x, (y, z) in set(self.items()):
            if now - y > self._timeout:
                del self[x]


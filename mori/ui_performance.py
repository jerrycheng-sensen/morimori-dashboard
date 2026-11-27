"""Per-browser UI read cache; scheduled checks always use the uncached store."""
from __future__ import annotations

import copy
import time
from concurrent.futures import ThreadPoolExecutor


class UIStore:
    """Cache only settings and encrypted credentials, never runner locks/runtime.

    Each browser session owns an instance. Writes retain GitHub's SHA conflict
    checks; failed writes invalidate the snapshot rather than hiding a conflict.
    """
    CACHEABLE = {"settings.json", "credentials.encrypted.json", "festival-model.json"}

    def __init__(self, store, ttl=30, clock=time.monotonic):
        self.store, self.ttl, self.clock = store, ttl, clock
        self.cache = {}

    def __getattr__(self, name):
        return getattr(self.store, name)

    def clear(self):
        self.cache.clear()

    def _cached(self, path, read):
        cached = self.cache.get(path)
        if cached is not None and self.clock() - cached[0] < self.ttl:
            return copy.deepcopy(cached[1])
        self.cache.pop(path, None)
        result = read()
        self.cache[path] = (self.clock(), copy.deepcopy(result))
        return result

    def settings(self):
        return self._cached("settings.json", self.store.settings)

    def read(self, path, default=None):
        if path not in self.CACHEABLE:
            return self.store.read(path, default)
        return self._cached(path, lambda: self.store.read(path, default))

    def write(self, path, data, sha, *args, **kwargs):
        try:
            new_sha = self.store.write(path, data, sha, *args, **kwargs)
        finally:
            self.cache.pop(path, None)
        if path in self.CACHEABLE:
            self.cache[path] = (self.clock(), (copy.deepcopy(data), new_sha))
        return new_sha


def fetch_accounts(accounts, fetch):
    """Independent network calls overlap, preserving selected-account order."""
    from mori.core import AppError
    reports, errors = [], []
    with ThreadPoolExecutor(max_workers=min(4, max(1, len(accounts)))) as pool:
        jobs = [(account, pool.submit(fetch, account)) for account in accounts]
        for account, job in jobs:
            try:
                reports.append(job.result())
            except AppError as exc:
                errors.append(f"{account['name']}：{exc}")
    return reports, errors

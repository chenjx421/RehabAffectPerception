from concurrent.futures import ThreadPoolExecutor

from src.rehab_affect import demo2_media_cache as cache_module


def test_lru_evicts_and_returns_detached_values():
    cache = cache_module.MediaResultCache(max_entries=2, max_bytes=8, ttl=60)
    value = {"faces": [1]}
    cache.put((1,), value, size=2)
    value["faces"].append(2)
    cache.put((2,), b"bb", size=2)
    got = cache.get((1,))
    got["faces"].append(3)
    cache.put((3,), b"cc", size=2)
    assert cache.get((2,)) is None
    assert cache.get((1,)) == {"faces": [1]}


def test_size_budget_replacement_and_oversized_entries():
    cache = cache_module.MediaResultCache(max_entries=10, max_bytes=4, ttl=60)
    cache.put((1,), b"aa", size=2)
    cache.put((2,), b"bb", size=2)
    cache.put((1,), b"ccc", size=3)
    assert cache.get((2,)) is None
    assert cache._bytes == 3
    cache.put((3,), b"12345", size=5)
    assert cache.get((3,)) is None
    assert cache._bytes == 3


def test_expiry_and_disabled_cache(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(cache_module.time, "monotonic", lambda: now[0])
    cache = cache_module.MediaResultCache(max_entries=2, max_bytes=4, ttl=5)
    cache.put((1,), b"aa", size=2)
    now[0] = 105
    assert cache.get((1,)) is None
    assert cache._bytes == 0
    disabled = cache_module.MediaResultCache(max_entries=2, max_bytes=4, ttl=0)
    disabled.put((1,), b"a", size=1)
    assert disabled.get((1,)) is None


def test_concurrent_access_stays_bounded():
    cache = cache_module.MediaResultCache(max_entries=4, max_bytes=8, ttl=60)

    def access(i):
        cache.put((i,), {"n": i}, size=2)
        found = cache.get((i,))
        assert found is None or found == {"n": i}

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(access, range(1000)))
    assert len(cache._entries) <= 4
    assert cache._bytes <= 8

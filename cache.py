from collections import OrderedDict
from config import CACHE_SIZE

_cache = OrderedDict()

def cache_get(key):
    if key in _cache:
        _cache.move_to_end(key)
        return _cache[key]
    return None

def cache_set(key, value):
    if key in _cache:
        _cache.move_to_end(key)
    _cache[key] = value
    if len(_cache) > CACHE_SIZE:
        oldest = next(iter(_cache))
        del _cache[oldest]

def cache_clear():
    _cache.clear()

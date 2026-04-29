"""Performance timing decorator for debug-level profiling."""

import functools
import logging
import time

logger = logging.getLogger(__name__)


def timed(func):
    """Decorator that logs function execution time at DEBUG level.

    Logs the qualified function name, arguments summary, and elapsed time.
    No-op overhead when DEBUG logging is disabled.
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        if not logger.isEnabledFor(logging.DEBUG):
            return func(*args, **kwargs)

        name = func.__qualname__
        t0 = time.perf_counter()
        try:
            result = func(*args, **kwargs)
            elapsed = time.perf_counter() - t0
            logger.debug(f"{name}: {elapsed:.3f}s")
            return result
        except Exception:
            elapsed = time.perf_counter() - t0
            logger.debug(f"{name}: {elapsed:.3f}s (raised)")
            raise

    return wrapper

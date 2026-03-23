"""Base utilities for venture integrations."""

import time
import functools


def retry(max_attempts=3, base_delay=1.0, exceptions=(Exception,)):
    """Decorator: retry with exponential backoff on specified exceptions."""
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            last_exc = None
            for attempt in range(max_attempts):
                try:
                    return fn(*args, **kwargs)
                except exceptions as e:
                    last_exc = e
                    if attempt < max_attempts - 1:
                        time.sleep(base_delay * (2 ** attempt))
            return error_response(str(last_exc))
        return wrapper
    return decorator


def error_response(error: str, url: str = "") -> dict:
    """Standard error response format."""
    return {"success": False, "error": error, "url": url}


def ok_response(url: str = "", **kwargs) -> dict:
    """Standard success response format."""
    return {"success": True, "error": "", "url": url, **kwargs}

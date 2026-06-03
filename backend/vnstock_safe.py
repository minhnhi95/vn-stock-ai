"""
Patch vnstock 4.x: ngăn sys.exit() khi rate limit + helper safe_call.

vnstock free tier 20 req/min hit limit → thư viện call `sys.exit()` giết worker.
Patch CleanErrorContext.__exit__ để propagate RateLimitExceeded normally thay vì sys.exit.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Optional, TypeVar

log = logging.getLogger(__name__)
T = TypeVar("T")
_patched = False


def patch_vnstock_quota() -> None:
    """Idempotent: chỉ patch 1 lần."""
    global _patched
    if _patched:
        return
    try:
        import vnai.beam.quota as _vnq
    except ImportError:
        return

    _orig_exit = _vnq.CleanErrorContext.__exit__

    def _safe_exit(self, exc_type, exc_val, exc_tb):
        # Nếu là RateLimitExceeded → KHÔNG gọi sys.exit, để nó propagate.
        if exc_type is not None and issubclass(exc_type, _vnq.RateLimitExceeded):
            return False  # exception propagates lên caller
        return _orig_exit(self, exc_type, exc_val, exc_tb)

    _vnq.CleanErrorContext.__exit__ = _safe_exit
    _patched = True
    log.info("[vnstock_safe] Patched vnai.beam.quota.CleanErrorContext to prevent sys.exit on rate limit")


def safe_call(fn: Callable[..., T], *args: Any, default: Optional[T] = None, **kwargs: Any) -> Optional[T]:
    """
    Gọi fn(*args, **kwargs) an toàn. Trả về default nếu gặp:
    - SystemExit (do vnstock cũ trước khi patch áp dụng)
    - RateLimitExceeded
    - Bất kỳ exception nào khác → log + trả default
    """
    try:
        return fn(*args, **kwargs)
    except SystemExit as e:
        log.warning(f"[vnstock_safe] SystemExit caught from {fn.__name__}: {str(e)[:100]}")
        return default
    except Exception as e:
        msg = str(e)
        if "Rate limit" in msg or "rate limit" in msg.lower():
            log.warning(f"[vnstock_safe] Rate limited on {fn.__name__}")
            return default
        log.warning(f"[vnstock_safe] {fn.__name__} failed: {msg[:200]}")
        return default


# Apply patch ngay khi module được import
patch_vnstock_quota()

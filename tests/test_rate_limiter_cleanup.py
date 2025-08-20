import time
import types
import sys

# Stub heavy modules imported by app.api.__init__ to avoid pulling large dependencies
sys.modules.setdefault("app.api.routes", types.ModuleType("app.api.routes"))
sys.modules.setdefault("app.api.services", types.ModuleType("app.api.services"))

from app.api.middleware.rate_limiter import RateLimitConfig, RateLimiter, RequestTracker


def test_cleanup_old_trackers_prunes_based_on_max_age() -> None:
    rl = RateLimiter(RateLimitConfig())
    now = time.time()
    rl.ip_trackers = {
        "old": RequestTracker(last_seen=now - 120),
        "new": RequestTracker(last_seen=now),
    }
    rl.user_trackers = {
        "old_user": RequestTracker(last_seen=now - 120),
        "new_user": RequestTracker(last_seen=now),
    }

    rl.cleanup_old_trackers(max_age=60)

    assert "old" not in rl.ip_trackers
    assert "new" in rl.ip_trackers
    assert "old_user" not in rl.user_trackers
    assert "new_user" in rl.user_trackers

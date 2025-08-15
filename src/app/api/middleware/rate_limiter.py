from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field

from fastapi import HTTPException, Request, status


@dataclass
class RateLimitConfig:
    requests_per_minute: int = 60
    requests_per_hour: int = 1000
    burst_size: int = 10
    enable_ip_tracking: bool = True
    enable_user_tracking: bool = True
    redis_url: str | None = None


@dataclass
class RequestTracker:
    tokens: float | None = None
    capacity: int | None = None
    last_refill: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)

    def is_allowed(self, now: float, limit: int, window: float, burst: int) -> bool:
        cap = int(limit) + int(max(burst, 0))
        rate = float(limit) / float(window)

        if self.capacity != cap:
            self.capacity = cap
            if self.tokens is None:
                self.tokens = float(cap)
            else:
                self.tokens = min(float(cap), float(self.tokens))

        elapsed = max(0.0, now - self.last_refill)
        if self.tokens is None:
            self.tokens = float(cap)
        if elapsed > 0.0:
            self.tokens = min(float(self.capacity), float(self.tokens) + rate * elapsed)
            self.last_refill = now

        self.last_seen = now

        if self.tokens >= 1.0:
            self.tokens -= 1.0
            return True
        return False


class RateLimiter:
    def __init__(self, config: RateLimitConfig):
        self.config = config
        self.ip_trackers: dict[str, RequestTracker] = defaultdict(RequestTracker)
        self.user_trackers: dict[str, RequestTracker] = defaultdict(RequestTracker)

    async def check_rate_limit(self, request: Request, user_id: str | None = None) -> None:
        now = time.time()
        client_ip = request.client.host if request.client else "unknown"

        if self.config.enable_ip_tracking:
            ip_tracker = self.ip_trackers[client_ip]
            if not ip_tracker.is_allowed(
                now, self.config.requests_per_minute, 60.0, self.config.burst_size
            ):
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail={"error": "rate_limit_exceeded", "retry_after": 60, "limit_type": "ip"},
                )

        if self.config.enable_user_tracking and user_id:
            user_tracker = self.user_trackers[user_id]
            if not user_tracker.is_allowed(
                now, self.config.requests_per_hour, 3600.0, self.config.burst_size * 2
            ):
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail={
                        "error": "rate_limit_exceeded",
                        "retry_after": 3600,
                        "limit_type": "user",
                    },
                )

    def cleanup_old_trackers(self, max_age: float = 7200.0) -> None:
        now = time.time()
        self.ip_trackers = {
            ip: tr for ip, tr in self.ip_trackers.items() if now - tr.last_seen < max_age
        }
        self.user_trackers = {
            uid: tr for uid, tr in self.user_trackers.items() if now - tr.last_seen < max_age
        }

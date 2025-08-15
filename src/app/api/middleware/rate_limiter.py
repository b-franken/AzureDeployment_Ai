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
    timestamps: list[float] = field(default_factory=list)
    burst_tokens: int = 10

    def is_allowed(self, current_time: float, limit: int, window: float, burst: int) -> bool:
        self.timestamps = [t for t in self.timestamps if current_time - t < window]

        if len(self.timestamps) >= limit:
            return False

        if len(self.timestamps) >= limit - burst and self.burst_tokens <= 0:
            return False

        if len(self.timestamps) >= limit - burst:
            self.burst_tokens -= 1

        self.timestamps.append(current_time)

        if current_time - self.timestamps[0] > window and self.burst_tokens < burst:
            self.burst_tokens = min(burst, self.burst_tokens + 1)

        return True


class RateLimiter:
    def __init__(self, config: RateLimitConfig):
        self.config = config
        self.ip_trackers: dict[str, RequestTracker] = defaultdict(RequestTracker)
        self.user_trackers: dict[str, RequestTracker] = defaultdict(RequestTracker)

    async def check_rate_limit(self, request: Request, user_id: str | None = None) -> None:
        current_time = time.time()
        client_ip = request.client.host if request.client else "unknown"

        if self.config.enable_ip_tracking:
            ip_tracker = self.ip_trackers[client_ip]
            if not ip_tracker.is_allowed(
                current_time, self.config.requests_per_minute, 60.0, self.config.burst_size
            ):
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail={"error": "rate_limit_exceeded", "retry_after": 60, "limit_type": "ip"},
                )

        if self.config.enable_user_tracking and user_id:
            user_tracker = self.user_trackers[user_id]
            if not user_tracker.is_allowed(
                current_time, self.config.requests_per_hour, 3600.0, self.config.burst_size * 2
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
        current_time = time.time()

        self.ip_trackers = {
            ip: tracker
            for ip, tracker in self.ip_trackers.items()
            if tracker.timestamps and current_time - tracker.timestamps[-1] < max_age
        }

        self.user_trackers = {
            user: tracker
            for user, tracker in self.user_trackers.items()
            if tracker.timestamps and current_time - tracker.timestamps[-1] < max_age
        }

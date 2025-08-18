from __future__ import annotations

import time
from collections import defaultdict
from collections.abc import Awaitable
from dataclasses import dataclass, field
from typing import Any, cast

import redis.asyncio as redis
from fastapi import HTTPException, Request, status
from redis.asyncio.client import Redis as AsyncRedis
from redis.exceptions import NoScriptError, ResponseError


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


class RedisTokenBucket:
    def __init__(self, redis_url: str, namespace: str = "rl"):
        self.pool = redis.ConnectionPool.from_url(
            redis_url, decode_responses=False, max_connections=100
        )
        self._client: AsyncRedis | None = None
        self.namespace = namespace
        self._sha: str | None = None
        self._script = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local limit = tonumber(ARGV[2])
local window = tonumber(ARGV[3])
local burst = tonumber(ARGV[4])
local cap = math.floor(limit + math.max(burst, 0))
local rate = limit / window
local data = redis.call('HMGET', key, 'tokens', 'capacity', 'last_refill')
local tokens = tonumber(data[1])
local capacity = tonumber(data[2])
local last_refill = tonumber(data[3])
if capacity ~= cap then
  capacity = cap
  if tokens == nil then
    tokens = cap
  else
    if tokens > cap then tokens = cap end
  end
end
if tokens == nil then tokens = cap end
if last_refill == nil then last_refill = now end
local elapsed = now - last_refill
if elapsed < 0 then elapsed = 0 end
if elapsed > 0 then
  tokens = tokens + rate * elapsed
  if tokens > capacity then tokens = capacity end
  last_refill = now
end
local allowed = 0
if tokens >= 1.0 then
  tokens = tokens - 1.0
  allowed = 1
end
redis.call('HSET', key, 'tokens', tokens, 'capacity', capacity, 'last_refill', last_refill)
local ttl = math.ceil(math.max(window * 2, 60))
redis.call('EXPIRE', key, ttl)
return allowed
"""

    async def _client_ready(self) -> AsyncRedis:
        if self._client is None:
            self._client = redis.Redis(connection_pool=self.pool)
            await self._client.ping()
        if self._sha is None:
            self._sha = await self._client.script_load(self._script)
        return self._client

    def _full_key(self, bucket: str) -> str:
        return f"{self.namespace}:{bucket}"

    async def is_allowed(self, bucket: str, limit: int, window: float, burst: int) -> bool:
        client = await self._client_ready()
        key = self._full_key(bucket)
        now_s = f"{time.time():.6f}"
        sha = self._sha
        if sha is None:
            self._sha = await client.script_load(self._script)
            sha = self._sha
        if sha is None:
            raise RuntimeError("Failed to load rate limiter script in Redis")
        try:
            call = client.evalsha(
                sha, 1, key, now_s, str(float(limit)), str(float(window)), str(int(burst))
            )
            res: Any = await cast(Awaitable[Any], call)
        except (NoScriptError, ResponseError):
            self._sha = await client.script_load(self._script)
            sha2 = self._sha
            if sha2 is None:
                raise RuntimeError("Failed to reload rate limiter script in Redis") from None
            call2 = client.evalsha(
                sha2, 1, key, now_s, str(float(limit)), str(float(window)), str(int(burst))
            )
            res = await cast(Awaitable[Any], call2)
        return bool(int(res))


class RateLimiter:
    def __init__(self, config: RateLimitConfig):
        self.config = config
        self.ip_trackers: dict[str, RequestTracker] = defaultdict(RequestTracker)
        self.user_trackers: dict[str, RequestTracker] = defaultdict(RequestTracker)
        self.redis_backend: RedisTokenBucket | None = (
            RedisTokenBucket(config.redis_url) if config.redis_url else None
        )

    async def check_rate_limit(self, request: Request, user_id: str | None = None) -> None:
        now = time.time()
        client_ip = request.client.host if request.client else "unknown"
        if self.redis_backend is not None:
            if self.config.enable_ip_tracking:
                ok = await self.redis_backend.is_allowed(
                    f"ip:1m:{client_ip}",
                    self.config.requests_per_minute,
                    60.0,
                    self.config.burst_size,
                )
                if not ok:
                    raise HTTPException(
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        detail={
                            "error": "rate_limit_exceeded",
                            "retry_after": 60,
                            "limit_type": "ip",
                        },
                    )
            if self.config.enable_user_tracking and user_id:
                ok = await self.redis_backend.is_allowed(
                    f"user:1h:{user_id}",
                    self.config.requests_per_hour,
                    3600.0,
                    self.config.burst_size * 2,
                )
                if not ok:
                    raise HTTPException(
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        detail={
                            "error": "rate_limit_exceeded",
                            "retry_after": 3600,
                            "limit_type": "user",
                        },
                    )
            return
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

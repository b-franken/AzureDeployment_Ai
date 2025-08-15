from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, cast

from app.cache.redis_cache import CacheManager


class JobStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    RETRYING = "retrying"


class JobPriority(Enum):
    LOW = 0
    NORMAL = 1
    HIGH = 2
    CRITICAL = 3


@dataclass
class Job:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    status: JobStatus = JobStatus.PENDING
    priority: JobPriority = JobPriority.NORMAL
    max_retries: int = 3
    retry_count: int = 0
    retry_delay: int = 60
    timeout: int = 300
    created_at: datetime = field(default_factory=datetime.utcnow)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None
    result: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)


class JobQueue:
    def __init__(
        self,
        cache: CacheManager,
        queue_name: str = "default",
        max_workers: int = 10,
        poll_interval: int = 1,
    ):
        self.cache = cache
        self.queue_name = queue_name
        self.max_workers = max_workers
        self.poll_interval = poll_interval
        self.handlers: dict[str, Callable[[Job], Coroutine[Any, Any, Any]]] = {}
        self.workers: list[asyncio.Task] = []
        self._running = False
        self._lock = asyncio.Lock()

    def register_handler(
        self, job_name: str, handler: Callable[[Job], Coroutine[Any, Any, Any]]
    ) -> None:
        self.handlers[job_name] = handler

    async def enqueue(
        self,
        job_name: str,
        payload: dict[str, Any] | None = None,
        priority: JobPriority = JobPriority.NORMAL,
        max_retries: int = 3,
        timeout: int = 300,
        delay: int = 0,
    ) -> str:
        job = Job(
            name=job_name,
            payload=payload or {},
            priority=priority,
            max_retries=max_retries,
            timeout=timeout,
        )

        if delay > 0:
            job.metadata["scheduled_for"] = (
                datetime.utcnow() + timedelta(seconds=delay)
            ).isoformat()

        queue_key = self._get_queue_key(priority)
        await self.cache.lpush(queue_key, self._serialize_job(job))
        await self.cache.hset(
            f"jobs:{self.queue_name}",
            job.id,
            self._serialize_job(job),
        )

        return job.id

    async def get_job(self, job_id: str) -> Job | None:
        data = await self.cache.hget(f"jobs:{self.queue_name}", job_id)
        return self._deserialize_job(data) if data else None

    async def cancel_job(self, job_id: str) -> bool:
        job = await self.get_job(job_id)
        if not job or job.status not in [JobStatus.PENDING, JobStatus.RETRYING]:
            return False

        job.status = JobStatus.CANCELLED
        job.completed_at = datetime.utcnow()
        await self._update_job(job)
        return True

    async def start(self) -> None:
        async with self._lock:
            if self._running:
                return

            self._running = True
            for i in range(self.max_workers):
                worker = asyncio.create_task(self._worker(i))
                self.workers.append(worker)

    async def stop(self) -> None:
        async with self._lock:
            self._running = False
            for worker in self.workers:
                worker.cancel()

            await asyncio.gather(*self.workers, return_exceptions=True)
            self.workers.clear()

    async def _worker(self, worker_id: int) -> None:
        while self._running:
            try:
                job = await self._get_next_job()
                if job:
                    await self._process_job(job)
                else:
                    await asyncio.sleep(self.poll_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"Worker {worker_id} error: {e}")
                await asyncio.sleep(self.poll_interval)

    async def _get_next_job(self) -> Job | None:
        for priority in sorted(JobPriority, key=lambda p: p.value, reverse=True):
            queue_key = self._get_queue_key(priority)
            data = await self.cache.rpop(queue_key)
            if data:
                job = self._deserialize_job(data)
                if job and self._should_process_job(job):
                    return job
                elif job:
                    await self.cache.lpush(queue_key, self._serialize_job(job))

        return None

    async def _process_job(self, job: Job) -> None:
        handler = self.handlers.get(job.name)
        if not handler:
            job.status = JobStatus.FAILED
            job.error = f"No handler registered for job: {job.name}"
            job.completed_at = datetime.utcnow()
            await self._update_job(job)
            return

        job.status = JobStatus.RUNNING
        job.started_at = datetime.utcnow()
        await self._update_job(job)

        try:
            result = await asyncio.wait_for(handler(job), timeout=job.timeout)
            job.status = JobStatus.COMPLETED
            job.result = result
            job.completed_at = datetime.utcnow()
        except TimeoutError:
            job.status = JobStatus.FAILED
            job.error = f"Job timed out after {job.timeout} seconds"
            job.completed_at = datetime.utcnow()
            await self._retry_job(job)
        except Exception as e:
            job.status = JobStatus.FAILED
            job.error = str(e)
            job.completed_at = datetime.utcnow()
            await self._retry_job(job)

        await self._update_job(job)

    async def _retry_job(self, job: Job) -> None:
        if job.retry_count < job.max_retries:
            job.retry_count += 1
            job.status = JobStatus.RETRYING
            job.metadata["retry_at"] = (
                datetime.utcnow() + timedelta(seconds=job.retry_delay * job.retry_count)
            ).isoformat()

            queue_key = self._get_queue_key(job.priority)
            await self.cache.lpush(queue_key, self._serialize_job(job))

    async def _update_job(self, job: Job) -> None:
        await self.cache.hset(
            f"jobs:{self.queue_name}",
            job.id,
            self._serialize_job(job),
        )

        if job.status in [
            JobStatus.COMPLETED,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
        ]:
            ttl = 86400
            await self.cache.expire(f"jobs:{self.queue_name}:{job.id}", ttl)

    def _get_queue_key(self, priority: JobPriority) -> str:
        return f"queue:{self.queue_name}:{priority.name.lower()}"

    def _serialize_job(self, job: Job) -> str:
        data: dict[str, Any] = {
            "id": job.id,
            "name": job.name,
            "payload": job.payload,
            "status": job.status.value,
            "priority": job.priority.value,
            "max_retries": job.max_retries,
            "retry_count": job.retry_count,
            "retry_delay": job.retry_delay,
            "timeout": job.timeout,
            "created_at": job.created_at.isoformat(),
            "started_at": job.started_at.isoformat() if job.started_at else None,
            "completed_at": (job.completed_at.isoformat() if job.completed_at else None),
            "error": job.error,
            "result": job.result,
            "metadata": job.metadata,
        }
        return json.dumps(data)

    def _deserialize_job(self, data: str | dict[str, Any]) -> Job:
        if isinstance(data, str):
            parsed = json.loads(data)
            if not isinstance(parsed, dict):
                raise ValueError("invalid job data")
            d = cast(dict[str, Any], parsed)
        else:
            d = data

        payload_raw = d.get("payload") or {}
        payload = payload_raw if isinstance(payload_raw, dict) else {}

        metadata_raw = d.get("metadata") or {}
        metadata = metadata_raw if isinstance(metadata_raw, dict) else {}

        status_val = d.get("status")
        status = (
            JobStatus(status_val) if isinstance(status_val, str) else JobStatus(str(status_val))
        )

        priority_val = d.get("priority")
        if isinstance(priority_val, int):
            priority = JobPriority(priority_val)
        elif isinstance(priority_val, str):
            if priority_val.isdigit():
                priority = JobPriority(int(priority_val))
            else:
                priority = JobPriority[priority_val.upper()]
        else:
            priority = JobPriority.NORMAL

        created_at_str = str(d.get("created_at"))
        started_at_str = d.get("started_at")
        completed_at_str = d.get("completed_at")

        return Job(
            id=str(d.get("id")),
            name=str(d.get("name", "")),
            payload=payload,
            status=status,
            priority=priority,
            max_retries=int(d.get("max_retries", 0)),
            retry_count=int(d.get("retry_count", 0)),
            retry_delay=int(d.get("retry_delay", 0)),
            timeout=int(d.get("timeout", 0)),
            created_at=datetime.fromisoformat(created_at_str),
            started_at=(datetime.fromisoformat(str(started_at_str)) if started_at_str else None),
            completed_at=(
                datetime.fromisoformat(str(completed_at_str)) if completed_at_str else None
            ),
            error=(str(d.get("error")) if d.get("error") is not None else None),
            result=d.get("result"),
            metadata=metadata,
        )

    def _should_process_job(self, job: Job) -> bool:
        if job.status == JobStatus.CANCELLED:
            return False

        if "scheduled_for" in job.metadata:
            scheduled_time = datetime.fromisoformat(job.metadata["scheduled_for"])
            if datetime.utcnow() < scheduled_time:
                return False

        if job.status == JobStatus.RETRYING and "retry_at" in job.metadata:
            retry_time = datetime.fromisoformat(job.metadata["retry_at"])
            if datetime.utcnow() < retry_time:
                return False

        return True

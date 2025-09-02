"""Dynamic batching processor for embeddings to reduce API calls."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class BatchRequest:
    """A single embedding request within a batch."""

    texts: list[str]
    future: asyncio.Future[list[list[float]]]
    timestamp: float


class DynamicBatchProcessor:
    """
    Collects embedding requests and batches them together to reduce API calls.

    This processor waits for a short time (batch_wait_ms) to collect multiple
    requests before sending them as a single batch to the embedding service.
    """

    def __init__(
        self,
        embed_fn: Callable[[list[str]], Awaitable[list[list[float]]]],
        batch_size: int = 128,
        batch_wait_ms: int = 50,
        max_queue_size: int = 1000,
    ) -> None:
        self._embed_fn = embed_fn
        self._batch_size = batch_size
        self._batch_wait_ms = batch_wait_ms / 1000.0
        self._max_queue_size = max_queue_size

        self._queue: list[BatchRequest] = []
        self._queue_lock = asyncio.Lock()
        self._processor_task: asyncio.Task[None] | None = None
        self._shutdown = False

    async def start(self) -> None:
        """Start the batch processor."""
        if self._processor_task is None:
            self._processor_task = asyncio.create_task(self._process_batches())

    async def stop(self) -> None:
        """Stop the batch processor."""
        self._shutdown = True
        if self._processor_task:
            try:
                await self._processor_task
            except asyncio.CancelledError:
                pass
            self._processor_task = None

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Request embeddings for texts, will be batched with other concurrent requests."""
        if self._shutdown:

            return await self._embed_fn(texts)

        future: asyncio.Future[list[list[float]]] = asyncio.Future()
        request = BatchRequest(texts=texts, future=future, timestamp=time.time())

        async with self._queue_lock:
            if len(self._queue) >= self._max_queue_size:

                await self._process_immediate_batch()
            self._queue.append(request)

        return await future

    async def _process_batches(self) -> None:
        """Main processing loop that batches and sends requests."""
        while not self._shutdown:
            try:
                await asyncio.sleep(self._batch_wait_ms)
                await self._process_queued_requests()
            except Exception as e:
                logger.error(f"Error in batch processor: {e}")

    async def _process_queued_requests(self) -> None:
        """Process all queued requests by batching them."""
        async with self._queue_lock:
            if not self._queue:
                return

            requests = self._queue.copy()
            self._queue.clear()

        batches = self._create_batches(requests)

        for batch in batches:
            try:
                await self._process_batch(batch)
            except Exception as e:
                logger.error(f"Error processing batch: {e}")

                for request in batch:
                    if not request.future.done():
                        request.future.set_exception(e)

    async def _process_immediate_batch(self) -> None:
        """Process a batch immediately when queue is full."""
        if not self._queue:
            return

        batch_requests = self._queue[: self._batch_size]
        self._queue = self._queue[self._batch_size :]

        try:
            await self._process_batch(batch_requests)
        except Exception as e:
            logger.error(f"Error processing immediate batch: {e}")
            for request in batch_requests:
                if not request.future.done():
                    request.future.set_exception(e)

    def _create_batches(self, requests: list[BatchRequest]) -> list[list[BatchRequest]]:
        """Group requests into optimal batches."""
        if not requests:
            return []

        batches: list[list[BatchRequest]] = []
        current_batch: list[BatchRequest] = []
        current_batch_size = 0

        for request in requests:
            text_count = len(request.texts)

            if current_batch and current_batch_size + text_count > self._batch_size:
                batches.append(current_batch)
                current_batch = []
                current_batch_size = 0

            current_batch.append(request)
            current_batch_size += text_count

        if current_batch:
            batches.append(current_batch)

        return batches

    async def _process_batch(self, requests: list[BatchRequest]) -> None:
        """Process a batch of requests by combining all texts and distributing results."""
        if not requests:
            return

        all_texts: list[str] = []
        request_indices: list[tuple[int, int]] = []

        for request in requests:
            start_idx = len(all_texts)
            all_texts.extend(request.texts)
            end_idx = len(all_texts)
            request_indices.append((start_idx, end_idx))

        if not all_texts:
            for request in requests:
                if not request.future.done():
                    request.future.set_result([])
            return

        try:
            all_embeddings = await self._embed_fn(all_texts)

            for request, (start_idx, end_idx) in zip(requests, request_indices, strict=False):
                if not request.future.done():
                    request_embeddings = all_embeddings[start_idx:end_idx]
                    request.future.set_result(request_embeddings)

        except Exception as e:

            for request in requests:
                if not request.future.done():
                    request.future.set_exception(e)


_batch_processor: DynamicBatchProcessor | None = None


def get_batch_processor(
    embed_fn: Callable[[list[str]], Awaitable[list[list[float]]]],
    batch_size: int = 128,
    batch_wait_ms: int = 50,
) -> DynamicBatchProcessor:
    """Get or create a global batch processor instance."""
    global _batch_processor
    if _batch_processor is None:
        _batch_processor = DynamicBatchProcessor(embed_fn, batch_size, batch_wait_ms)
    return _batch_processor

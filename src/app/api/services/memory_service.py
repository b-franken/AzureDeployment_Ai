"""
Enhanced memory service for user conversation tracking with comprehensive logging and telemetry.

This service integrates with PostgreSQL to provide persistent user memory across chat sessions,
making the AI assistant smarter by maintaining context and learning from interactions.
"""

from __future__ import annotations

import time
from typing import Any

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from app.core.logging import get_logger
from app.memory.storage import AsyncMemoryStore, MessageRole, get_async_store
from app.observability.app_insights import app_insights

logger = get_logger(__name__)
tracer = trace.get_tracer(__name__)


class UserMemoryService:
    """
    Enhanced user memory service with comprehensive logging and Application Insights integration.

    Provides intelligent conversation memory management including:
    - Persistent storage across sessions
    - Smart memory trimming based on context relevance
    - Comprehensive telemetry and observability
    - Thread and agent-based conversation tracking
    """

    def __init__(self) -> None:
        self._store: AsyncMemoryStore | None = None
        self._initialization_lock = False

    async def _get_store(self) -> AsyncMemoryStore:
        """Get or initialize the async memory store with proper error handling."""
        if self._store is None and not self._initialization_lock:
            self._initialization_lock = True
            try:
                with tracer.start_as_current_span("memory.initialize") as span:
                    span.set_attribute("service", "memory")
                    start_time = time.perf_counter()

                    self._store = await get_async_store()

                    elapsed = time.perf_counter() - start_time
                    span.set_attribute("initialization_time_ms", round(elapsed * 1000, 2))

                    logger.info(
                        "Memory store initialized successfully",
                        extra={
                            "service": "memory",
                            "initialization_time_ms": round(elapsed * 1000, 2),
                            "max_memory": self._store.max_memory,
                            "max_total_memory": self._store.max_total_memory,
                        },
                    )

                    # Track initialization in Application Insights
                    app_insights.track_custom_event(
                        "MemoryStoreInitialized",
                        {
                            "initialization_time_ms": elapsed * 1000,
                            "max_memory": self._store.max_memory,
                            "max_total_memory": self._store.max_total_memory,
                        },
                    )

            except Exception as exc:
                logger.error(
                    "Failed to initialize memory store",
                    extra={"error": str(exc), "error_type": type(exc).__name__},
                    exc_info=True,
                )
                app_insights.track_exception(exc)
                raise
            finally:
                self._initialization_lock = False

        if self._store is None:
            raise RuntimeError("Memory store initialization failed")

        return self._store

    async def store_user_message(
        self,
        user_id: str,
        content: str,
        *,
        thread_id: str | None = None,
        session_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        """
        Store a user message with comprehensive telemetry.

        Args:
            user_id: Unique identifier for the user
            content: Message content
            thread_id: Optional thread identifier for conversation grouping
            session_id: Optional session identifier
            metadata: Additional metadata to store with the message

        Returns:
            Message ID from the database
        """
        with tracer.start_as_current_span("memory.store_user_message") as span:
            span.set_attribute("user_id", user_id)
            span.set_attribute("content_length", len(content))
            span.set_attribute("has_thread_id", thread_id is not None)
            span.set_attribute("has_metadata", metadata is not None)

            start_time = time.perf_counter()

            try:
                store = await self._get_store()

                # Enrich metadata with session information
                enriched_metadata = dict(metadata or {})
                if session_id:
                    enriched_metadata["session_id"] = session_id
                if thread_id:
                    enriched_metadata["thread_id"] = thread_id

                enriched_metadata.update(
                    {
                        "timestamp": time.time(),
                        "service_version": "2025.1",
                        "stored_by": "UserMemoryService",
                    }
                )

                message_id = await store.store_message(
                    user_id=user_id,
                    role=MessageRole.USER,
                    content=content,
                    metadata=enriched_metadata,
                    thread_id=thread_id,
                )

                elapsed = time.perf_counter() - start_time
                span.set_attribute("message_id", message_id)
                span.set_attribute("storage_time_ms", round(elapsed * 1000, 2))

                logger.info(
                    "User message stored successfully",
                    extra={
                        "user_id": user_id,
                        "message_id": message_id,
                        "content_length": len(content),
                        "thread_id": thread_id,
                        "session_id": session_id,
                        "storage_time_ms": round(elapsed * 1000, 2),
                    },
                )

                # Track in Application Insights
                app_insights.track_custom_event(
                    "UserMessageStored",
                    {
                        "user_id": user_id,
                        "message_id": str(message_id),
                        "content_length": len(content),
                        "storage_time_ms": elapsed * 1000,
                        "has_thread_id": thread_id is not None,
                    },
                )

                return message_id

            except Exception as exc:
                span.record_exception(exc)
                span.set_status(Status(StatusCode.ERROR, str(exc)))

                logger.error(
                    "Failed to store user message",
                    extra={
                        "user_id": user_id,
                        "content_length": len(content),
                        "error": str(exc),
                        "error_type": type(exc).__name__,
                    },
                    exc_info=True,
                )

                app_insights.track_exception(exc)
                raise

    async def store_assistant_message(
        self,
        user_id: str,
        content: str,
        *,
        thread_id: str | None = None,
        session_id: str | None = None,
        model_info: dict[str, Any] | None = None,
        tools_used: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        """
        Store an assistant message with model and tool usage information.

        Args:
            user_id: Unique identifier for the user
            content: Assistant response content
            thread_id: Optional thread identifier
            session_id: Optional session identifier
            model_info: Information about the model used (provider, model name, etc.)
            tools_used: List of tools that were executed
            metadata: Additional metadata

        Returns:
            Message ID from the database
        """
        with tracer.start_as_current_span("memory.store_assistant_message") as span:
            span.set_attribute("user_id", user_id)
            span.set_attribute("content_length", len(content))
            span.set_attribute("has_model_info", model_info is not None)
            span.set_attribute("tools_count", len(tools_used or []))

            start_time = time.perf_counter()

            try:
                store = await self._get_store()

                # Enrich metadata with assistant-specific information
                enriched_metadata = dict(metadata or {})
                if session_id:
                    enriched_metadata["session_id"] = session_id
                if model_info:
                    enriched_metadata["model_info"] = model_info
                if tools_used:
                    enriched_metadata["tools_used"] = tools_used

                enriched_metadata.update(
                    {
                        "timestamp": time.time(),
                        "service_version": "2025.1",
                        "stored_by": "UserMemoryService",
                        "response_type": "assistant",
                    }
                )

                message_id = await store.store_message(
                    user_id=user_id,
                    role=MessageRole.ASSISTANT,
                    content=content,
                    metadata=enriched_metadata,
                    thread_id=thread_id,
                )

                elapsed = time.perf_counter() - start_time
                span.set_attribute("message_id", message_id)
                span.set_attribute("storage_time_ms", round(elapsed * 1000, 2))

                logger.info(
                    "Assistant message stored successfully",
                    extra={
                        "user_id": user_id,
                        "message_id": message_id,
                        "content_length": len(content),
                        "thread_id": thread_id,
                        "session_id": session_id,
                        "tools_used": tools_used or [],
                        "model_provider": model_info.get("provider") if model_info else None,
                        "model_name": model_info.get("model") if model_info else None,
                        "storage_time_ms": round(elapsed * 1000, 2),
                    },
                )

                # Track in Application Insights
                app_insights.track_custom_event(
                    "AssistantMessageStored",
                    {
                        "user_id": user_id,
                        "message_id": str(message_id),
                        "content_length": len(content),
                        "storage_time_ms": elapsed * 1000,
                        "tools_count": len(tools_used or []),
                        "model_provider": model_info.get("provider") if model_info else None,
                        "model_name": model_info.get("model") if model_info else None,
                    },
                )

                return message_id

            except Exception as exc:
                span.record_exception(exc)
                span.set_status(Status(StatusCode.ERROR, str(exc)))

                logger.error(
                    "Failed to store assistant message",
                    extra={
                        "user_id": user_id,
                        "content_length": len(content),
                        "error": str(exc),
                        "error_type": type(exc).__name__,
                    },
                    exc_info=True,
                )

                app_insights.track_exception(exc)
                raise

    async def get_user_conversation_history(
        self,
        user_id: str,
        *,
        limit: int | None = None,
        thread_id: str | None = None,
        include_metadata: bool = False,
    ) -> list[dict[str, Any]]:
        """
        Retrieve user conversation history with intelligent filtering.

        Args:
            user_id: User identifier
            limit: Maximum number of messages to return
            thread_id: Filter by specific thread
            include_metadata: Whether to include message metadata

        Returns:
            List of conversation messages in chronological order
        """
        with tracer.start_as_current_span("memory.get_conversation_history") as span:
            span.set_attribute("user_id", user_id)
            span.set_attribute("limit", limit or -1)
            span.set_attribute("has_thread_id", thread_id is not None)
            span.set_attribute("include_metadata", include_metadata)

            start_time = time.perf_counter()

            try:
                store = await self._get_store()

                messages = await store.get_user_memory(
                    user_id=user_id,
                    limit=limit,
                    include_metadata=include_metadata,
                    thread_id=thread_id,
                )

                elapsed = time.perf_counter() - start_time
                span.set_attribute("messages_count", len(messages))
                span.set_attribute("retrieval_time_ms", round(elapsed * 1000, 2))

                logger.info(
                    "Retrieved user conversation history",
                    extra={
                        "user_id": user_id,
                        "messages_count": len(messages),
                        "thread_id": thread_id,
                        "limit": limit,
                        "retrieval_time_ms": round(elapsed * 1000, 2),
                    },
                )

                # Track retrieval in Application Insights
                app_insights.track_custom_event(
                    "ConversationHistoryRetrieved",
                    {
                        "user_id": user_id,
                        "messages_count": len(messages),
                        "retrieval_time_ms": elapsed * 1000,
                        "has_thread_filter": thread_id is not None,
                    },
                )

                return messages

            except Exception as exc:
                span.record_exception(exc)
                span.set_status(Status(StatusCode.ERROR, str(exc)))

                logger.error(
                    "Failed to retrieve conversation history",
                    extra={"user_id": user_id, "error": str(exc), "error_type": type(exc).__name__},
                    exc_info=True,
                )

                app_insights.track_exception(exc)
                raise

    async def search_user_messages(
        self, user_id: str, search_query: str, *, limit: int = 10, thread_id: str | None = None
    ) -> list[dict[str, Any]]:
        """
        Search through user's message history using full-text search.

        Args:
            user_id: User identifier
            search_query: Text to search for
            limit: Maximum results to return
            thread_id: Optional thread filter

        Returns:
            List of matching messages with relevance scoring
        """
        with tracer.start_as_current_span("memory.search_messages") as span:
            span.set_attribute("user_id", user_id)
            span.set_attribute("search_query_length", len(search_query))
            span.set_attribute("limit", limit)

            start_time = time.perf_counter()

            try:
                store = await self._get_store()

                results = await store.search_messages(
                    user_id=user_id, query=search_query, limit=limit, thread_id=thread_id
                )

                elapsed = time.perf_counter() - start_time
                span.set_attribute("results_count", len(results))
                span.set_attribute("search_time_ms", round(elapsed * 1000, 2))

                logger.info(
                    "Message search completed",
                    extra={
                        "user_id": user_id,
                        "search_query": search_query[:100],  # Log first 100 chars
                        "results_count": len(results),
                        "search_time_ms": round(elapsed * 1000, 2),
                    },
                )

                # Track search in Application Insights
                app_insights.track_custom_event(
                    "MessageSearchPerformed",
                    {
                        "user_id": user_id,
                        "results_count": len(results),
                        "search_time_ms": elapsed * 1000,
                        "query_length": len(search_query),
                    },
                )

                return results

            except Exception as exc:
                span.record_exception(exc)
                span.set_status(Status(StatusCode.ERROR, str(exc)))

                logger.error(
                    "Message search failed",
                    extra={
                        "user_id": user_id,
                        "search_query": search_query[:100],
                        "error": str(exc),
                        "error_type": type(exc).__name__,
                    },
                    exc_info=True,
                )

                app_insights.track_exception(exc)
                raise

    async def get_user_memory_stats(self, user_id: str) -> dict[str, Any]:
        """
        Get comprehensive statistics about user's memory usage.

        Args:
            user_id: User identifier

        Returns:
            Dictionary containing memory usage statistics
        """
        with tracer.start_as_current_span("memory.get_user_stats") as span:
            span.set_attribute("user_id", user_id)

            try:
                store = await self._get_store()

                message_count = await store.get_message_count(user_id)

                # Get recent activity (last 24 hours worth of messages)
                recent_messages = await store.get_user_memory(
                    user_id=user_id, limit=100, include_metadata=True
                )

                # Analyze message patterns
                user_messages = len([m for m in recent_messages if m["role"] == "user"])
                assistant_messages = len([m for m in recent_messages if m["role"] == "assistant"])

                stats = {
                    "user_id": user_id,
                    "total_messages": message_count,
                    "recent_user_messages": user_messages,
                    "recent_assistant_messages": assistant_messages,
                    "memory_utilization_percent": min(
                        100, (message_count / store.max_total_memory) * 100
                    ),
                    "max_memory_limit": store.max_total_memory,
                }

                span.set_attribute("total_messages", message_count)
                utilization = stats.get("memory_utilization_percent", 0)
                span.set_attribute(
                    "memory_utilization",
                    float(utilization) if isinstance(utilization, int | float | str) else 0.0,
                )

                logger.info("User memory statistics generated", extra={"user_id": user_id, **stats})

                # Track statistics generation
                app_insights.track_custom_event(
                    "UserMemoryStatsGenerated",
                    {
                        "user_id": user_id,
                        "total_messages": message_count,
                        "memory_utilization": stats["memory_utilization_percent"],
                    },
                )

                return stats

            except Exception as exc:
                span.record_exception(exc)
                span.set_status(Status(StatusCode.ERROR, str(exc)))

                logger.error(
                    "Failed to generate user memory statistics",
                    extra={"user_id": user_id, "error": str(exc), "error_type": type(exc).__name__},
                    exc_info=True,
                )

                app_insights.track_exception(exc)
                raise


# Global instance
_memory_service: UserMemoryService | None = None


def get_memory_service() -> UserMemoryService:
    """Get the global memory service instance."""
    global _memory_service
    if _memory_service is None:
        _memory_service = UserMemoryService()
    return _memory_service

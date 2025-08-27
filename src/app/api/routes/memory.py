"""
Memory management API endpoints with comprehensive logging and telemetry.

Provides REST endpoints for managing user conversation memory including:
- Conversation history retrieval
- Message search functionality
- Memory statistics and analytics
- Memory cleanup and management
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from pydantic import BaseModel, Field

from app.api.routes.chat import get_optional_user, get_user_email
from app.api.services.memory_service import get_memory_service
from app.observability.app_insights import app_insights

router = APIRouter(prefix="/memory", tags=["memory"])
logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


class ConversationHistoryRequest(BaseModel):
    """Request model for retrieving conversation history."""

    limit: int | None = Field(
        default=20, ge=1, le=100, description="Maximum number of messages to retrieve"
    )
    thread_id: str | None = Field(default=None, description="Filter by specific thread ID")
    include_metadata: bool = Field(
        default=False, description="Include message metadata in response"
    )


class MessageSearchRequest(BaseModel):
    """Request model for searching messages."""

    query: str = Field(min_length=2, max_length=200, description="Search query text")
    limit: int = Field(default=10, ge=1, le=50, description="Maximum number of results to return")
    thread_id: str | None = Field(default=None, description="Filter by specific thread ID")


class ConversationHistoryResponse(BaseModel):
    """Response model for conversation history."""

    user_id: str
    messages: list[dict[str, Any]]
    total_count: int
    thread_id: str | None
    has_more: bool


class MessageSearchResponse(BaseModel):
    """Response model for message search."""

    user_id: str
    query: str
    results: list[dict[str, Any]]
    total_found: int


class UserMemoryStatsResponse(BaseModel):
    """Response model for user memory statistics."""

    user_id: str
    total_messages: int
    recent_user_messages: int
    recent_assistant_messages: int
    memory_utilization_percent: float
    max_memory_limit: int


@router.get("/history", response_model=ConversationHistoryResponse)
async def get_conversation_history(
    request: Request,
    current_user: Annotated[dict[str, Any], Depends(get_optional_user)],
    limit: int = Query(default=20, ge=1, le=100, description="Maximum messages to return"),
    thread_id: str | None = Query(default=None, description="Filter by thread ID"),
    include_metadata: bool = Query(default=False, description="Include message metadata"),
) -> ConversationHistoryResponse:
    """
    Retrieve user's conversation history with intelligent filtering and pagination.

    This endpoint provides access to the user's stored conversation history,
    enabling context-aware AI interactions across sessions.
    """
    with tracer.start_as_current_span("api.memory.history") as span:
        user_email = get_user_email(current_user)
        span.set_attribute("user_id", user_email)
        span.set_attribute("limit", limit)
        span.set_attribute("has_thread_filter", thread_id is not None)
        span.set_attribute("include_metadata", include_metadata)

        try:
            memory_service = get_memory_service()

            # Get conversation history
            messages = await memory_service.get_user_conversation_history(
                user_id=user_email,
                limit=limit,
                thread_id=thread_id,
                include_metadata=include_metadata,
            )

            # Get total message count for pagination info
            stats = await memory_service.get_user_memory_stats(user_email)
            total_count = stats["total_messages"]

            response = ConversationHistoryResponse(
                user_id=user_email,
                messages=messages,
                total_count=total_count,
                thread_id=thread_id,
                has_more=total_count > limit,
            )

            span.set_attribute("messages_returned", len(messages))
            span.set_attribute("total_messages", total_count)

            logger.info(
                "Conversation history retrieved successfully",
                extra={
                    "user_id": user_email,
                    "messages_returned": len(messages),
                    "total_messages": total_count,
                    "thread_id": thread_id,
                },
            )

            # Track API usage in Application Insights
            app_insights.track_custom_event(
                "ConversationHistoryAPICall",
                {
                    "user_id": user_email,
                    "messages_returned": len(messages),
                    "total_messages": total_count,
                    "has_thread_filter": thread_id is not None,
                },
            )

            return response

        except Exception as exc:
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, str(exc)))

            logger.error(
                "Failed to retrieve conversation history",
                extra={"user_id": user_email, "error": str(exc), "error_type": type(exc).__name__},
                exc_info=True,
            )

            app_insights.track_exception(exc)

            raise HTTPException(
                status_code=500, detail="Failed to retrieve conversation history"
            ) from exc


@router.post("/search", response_model=MessageSearchResponse)
async def search_messages(
    search_request: MessageSearchRequest,
    current_user: Annotated[dict[str, Any], Depends(get_optional_user)],
) -> MessageSearchResponse:
    """
    Search through user's message history using full-text search.

    This endpoint enables users to find specific conversations or topics
    from their interaction history, improving the AI's ability to reference
    past discussions and maintain context.
    """
    with tracer.start_as_current_span("api.memory.search") as span:
        user_email = get_user_email(current_user)
        span.set_attribute("user_id", user_email)
        span.set_attribute("search_query", search_request.query)
        span.set_attribute("limit", search_request.limit)

        try:
            memory_service = get_memory_service()

            # Perform message search
            results = await memory_service.search_user_messages(
                user_id=user_email,
                search_query=search_request.query,
                limit=search_request.limit,
                thread_id=search_request.thread_id,
            )

            response = MessageSearchResponse(
                user_id=user_email,
                query=search_request.query,
                results=results,
                total_found=len(results),
            )

            span.set_attribute("results_count", len(results))

            logger.info(
                "Message search completed successfully",
                extra={
                    "user_id": user_email,
                    "search_query": search_request.query,
                    "results_count": len(results),
                    "thread_id": search_request.thread_id,
                },
            )

            # Track search API usage
            app_insights.track_custom_event(
                "MessageSearchAPICall",
                {
                    "user_id": user_email,
                    "results_count": len(results),
                    "query_length": len(search_request.query),
                    "has_thread_filter": search_request.thread_id is not None,
                },
            )

            return response

        except Exception as exc:
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, str(exc)))

            logger.error(
                "Message search failed",
                extra={
                    "user_id": user_email,
                    "search_query": search_request.query,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
                exc_info=True,
            )

            app_insights.track_exception(exc)

            raise HTTPException(status_code=500, detail="Message search failed") from exc


@router.get("/stats", response_model=UserMemoryStatsResponse)
async def get_memory_stats(
    current_user: Annotated[dict[str, Any], Depends(get_optional_user)],
) -> UserMemoryStatsResponse:
    """
    Get comprehensive statistics about user's memory usage and patterns.

    Provides insights into conversation patterns, memory utilization,
    and analytics that can help improve the AI assistant's performance.
    """
    with tracer.start_as_current_span("api.memory.stats") as span:
        user_email = get_user_email(current_user)
        span.set_attribute("user_id", user_email)

        try:
            memory_service = get_memory_service()

            # Get comprehensive memory statistics
            stats = await memory_service.get_user_memory_stats(user_email)

            response = UserMemoryStatsResponse(**stats)

            span.set_attribute("total_messages", stats["total_messages"])
            span.set_attribute("memory_utilization", stats["memory_utilization_percent"])

            logger.info(
                "Memory statistics retrieved successfully", extra={"user_id": user_email, **stats}
            )

            # Track stats API usage
            app_insights.track_custom_event(
                "MemoryStatsAPICall",
                {
                    "user_id": user_email,
                    "total_messages": stats["total_messages"],
                    "memory_utilization": stats["memory_utilization_percent"],
                },
            )

            return response

        except Exception as exc:
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, str(exc)))

            logger.error(
                "Failed to retrieve memory statistics",
                extra={"user_id": user_email, "error": str(exc), "error_type": type(exc).__name__},
                exc_info=True,
            )

            app_insights.track_exception(exc)

            raise HTTPException(
                status_code=500, detail="Failed to retrieve memory statistics"
            ) from exc


@router.delete("/clear")
async def clear_user_memory(
    current_user: Annotated[dict[str, Any], Depends(get_optional_user)],
    thread_id: str | None = Query(default=None, description="Clear specific thread only"),
) -> JSONResponse:
    """
    Clear user's conversation memory.

    This endpoint allows users to clear their conversation history,
    either entirely or for a specific thread.

    WARNING: This action is irreversible.
    """
    with tracer.start_as_current_span("api.memory.clear") as span:
        user_email = get_user_email(current_user)
        span.set_attribute("user_id", user_email)
        span.set_attribute("thread_specific", thread_id is not None)

        try:
            memory_service = get_memory_service()

            if thread_id:
                # For thread-specific clearing, we'd need to implement this in the memory service
                # For now, return not implemented
                raise HTTPException(
                    status_code=501, detail="Thread-specific memory clearing not yet implemented"
                )
            # Clear all user memory
            store = await memory_service._get_store()
            deleted_count = await store.forget_user(user_email)

            span.set_attribute("deleted_count", deleted_count)

            logger.warning(
                "User memory cleared",
                extra={
                    "user_id": user_email,
                    "deleted_count": deleted_count,
                    "thread_id": thread_id,
                },
            )

            # Track memory clearing in Application Insights
            app_insights.track_custom_event(
                "UserMemoryCleared",
                {
                    "user_id": user_email,
                    "deleted_count": deleted_count,
                    "thread_specific": thread_id is not None,
                },
            )

            return JSONResponse(
                content={
                    "message": "Memory cleared successfully",
                    "deleted_messages": deleted_count,
                    "user_id": user_email,
                }
            )

        except HTTPException:
            raise
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, str(exc)))

            logger.error(
                "Failed to clear user memory",
                extra={"user_id": user_email, "error": str(exc), "error_type": type(exc).__name__},
                exc_info=True,
            )

            app_insights.track_exception(exc)

            raise HTTPException(status_code=500, detail="Failed to clear user memory") from exc

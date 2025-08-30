from __future__ import annotations

import json
from datetime import datetime, timedelta, UTC
from typing import Any, Dict, Optional, List
from dataclasses import dataclass

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from app.core.logging import get_logger
from app.core.data.repository import get_data_layer
from app.observability.app_insights import app_insights
from app.observability.distributed_tracing import get_service_tracer

tracer = trace.get_tracer(__name__)
logger = get_logger(__name__)


@dataclass
class AgentMemoryRecord:
    user_id: str
    agent_name: str
    context_key: str
    context_data: Dict[str, Any]
    correlation_id: str
    created_at: datetime = None
    updated_at: datetime = None
    expires_at: datetime = None
    metadata: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now(UTC)
        if self.updated_at is None:
            self.updated_at = datetime.now(UTC)
        if self.metadata is None:
            self.metadata = {}


class AgentMemoryPersistence:
    def __init__(self):
        self.db = get_data_layer()
        self._initialized = False
        self.logger = logger.bind(component="agent_memory")
        self.service_tracer = get_service_tracer("agent_memory_service")
    
    async def initialize(self) -> None:
        if self._initialized:
            return
            
        with tracer.start_as_current_span("agent_memory_initialize") as span:
            try:
                await self.db.initialize()
                await self.db.execute("""
                    CREATE TABLE IF NOT EXISTS agent_memory (
                        id BIGSERIAL PRIMARY KEY,
                        user_id TEXT NOT NULL,
                        agent_name TEXT NOT NULL,
                        context_key TEXT NOT NULL,
                        context_data JSONB NOT NULL,
                        correlation_id TEXT,
                        created_at TIMESTAMPTZ DEFAULT now(),
                        updated_at TIMESTAMPTZ DEFAULT now(),
                        expires_at TIMESTAMPTZ,
                        metadata JSONB DEFAULT '{}',
                        UNIQUE(user_id, agent_name, context_key)
                    );
                    
                    CREATE INDEX IF NOT EXISTS idx_agent_memory_user_agent 
                        ON agent_memory (user_id, agent_name);
                    
                    CREATE INDEX IF NOT EXISTS idx_agent_memory_expires 
                        ON agent_memory (expires_at) WHERE expires_at IS NOT NULL;
                    
                    CREATE INDEX IF NOT EXISTS idx_agent_memory_correlation 
                        ON agent_memory (correlation_id) WHERE correlation_id IS NOT NULL;
                    
                    CREATE INDEX IF NOT EXISTS idx_agent_memory_metadata_gin
                        ON agent_memory USING GIN (metadata);
                """)
                
                self._initialized = True
                span.set_status(Status(StatusCode.OK))
                self.logger.info("Agent memory persistence initialized")
                
            except Exception as e:
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                self.logger.error("Failed to initialize agent memory persistence", error=str(e), exc_info=True)
                raise
    
    async def store_context(
        self,
        user_id: str,
        agent_name: str,
        context_key: str,
        context_data: Dict[str, Any],
        correlation_id: str = None,
        ttl: timedelta = None,
        metadata: Dict[str, Any] = None
    ) -> bool:
        with tracer.start_as_current_span("agent_memory_store_context") as span:
            await self.initialize()
            
            span.set_attributes({
                "memory.user_id": user_id,
                "memory.agent_name": agent_name,
                "memory.context_key": context_key,
                "memory.has_ttl": ttl is not None,
                "memory.data_size": len(json.dumps(context_data))
            })
            
            try:
                expires_at = datetime.now(UTC) + ttl if ttl else None
                
                await self.db.execute("""
                    INSERT INTO agent_memory (user_id, agent_name, context_key, context_data, correlation_id, expires_at, metadata)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    ON CONFLICT (user_id, agent_name, context_key)
                    DO UPDATE SET 
                        context_data = EXCLUDED.context_data,
                        correlation_id = EXCLUDED.correlation_id,
                        updated_at = now(),
                        expires_at = EXCLUDED.expires_at,
                        metadata = EXCLUDED.metadata
                """, user_id, agent_name, context_key, json.dumps(context_data), 
                correlation_id, expires_at, json.dumps(metadata or {}))
                
                span.set_status(Status(StatusCode.OK))
                self.logger.info(
                    "Stored agent context",
                    user_id=user_id,
                    agent_name=agent_name,
                    context_key=context_key,
                    correlation_id=correlation_id
                )
                
                app_insights.track_custom_event(
                    "agent_context_stored",
                    {
                        "user_id": user_id,
                        "agent_name": agent_name,
                        "context_key": context_key,
                        "correlation_id": correlation_id
                    },
                    {
                        "data_size_bytes": len(json.dumps(context_data)),
                        "has_ttl": int(bool(ttl))
                    }
                )
                
                return True
                
            except Exception as e:
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                self.logger.error(
                    "Failed to store agent context",
                    user_id=user_id,
                    agent_name=agent_name,
                    context_key=context_key,
                    error=str(e),
                    exc_info=True
                )
                return False
    
    async def get_context(
        self,
        user_id: str,
        agent_name: str,
        context_key: str
    ) -> Optional[Dict[str, Any]]:
        with tracer.start_as_current_span("agent_memory_get_context") as span:
            await self.initialize()
            
            span.set_attributes({
                "memory.user_id": user_id,
                "memory.agent_name": agent_name,
                "memory.context_key": context_key
            })
            
            try:
                row = await self.db.fetchrow("""
                    SELECT context_data, correlation_id, created_at, updated_at, expires_at, metadata
                    FROM agent_memory 
                    WHERE user_id = $1 AND agent_name = $2 AND context_key = $3
                    AND (expires_at IS NULL OR expires_at > now())
                """, user_id, agent_name, context_key)
                
                if row:
                    context_data = json.loads(row['context_data'])
                    span.set_attributes({
                        "memory.found": True,
                        "memory.data_size": len(row['context_data'])
                    })
                    span.set_status(Status(StatusCode.OK))
                    
                    self.logger.debug(
                        "Retrieved agent context",
                        user_id=user_id,
                        agent_name=agent_name,
                        context_key=context_key
                    )
                    
                    return context_data
                else:
                    span.set_attribute("memory.found", False)
                    span.set_status(Status(StatusCode.OK))
                    return None
                    
            except Exception as e:
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                self.logger.error(
                    "Failed to get agent context",
                    user_id=user_id,
                    agent_name=agent_name,
                    context_key=context_key,
                    error=str(e),
                    exc_info=True
                )
                return None
    
    async def delete_context(
        self,
        user_id: str,
        agent_name: str,
        context_key: str = None
    ) -> bool:
        with tracer.start_as_current_span("agent_memory_delete_context") as span:
            await self.initialize()
            
            span.set_attributes({
                "memory.user_id": user_id,
                "memory.agent_name": agent_name,
                "memory.context_key": context_key or "*",
                "memory.delete_all": context_key is None
            })
            
            try:
                if context_key:
                    result = await self.db.execute("""
                        DELETE FROM agent_memory 
                        WHERE user_id = $1 AND agent_name = $2 AND context_key = $3
                    """, user_id, agent_name, context_key)
                else:
                    result = await self.db.execute("""
                        DELETE FROM agent_memory 
                        WHERE user_id = $1 AND agent_name = $2
                    """, user_id, agent_name)
                
                span.set_status(Status(StatusCode.OK))
                self.logger.info(
                    "Deleted agent context",
                    user_id=user_id,
                    agent_name=agent_name,
                    context_key=context_key,
                    deleted_rows=result
                )
                
                return True
                
            except Exception as e:
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                self.logger.error(
                    "Failed to delete agent context",
                    user_id=user_id,
                    agent_name=agent_name,
                    context_key=context_key,
                    error=str(e),
                    exc_info=True
                )
                return False
    
    async def list_contexts(
        self,
        user_id: str,
        agent_name: str = None
    ) -> List[Dict[str, Any]]:
        with tracer.start_as_current_span("agent_memory_list_contexts") as span:
            await self.initialize()
            
            span.set_attributes({
                "memory.user_id": user_id,
                "memory.agent_name": agent_name or "*"
            })
            
            try:
                if agent_name:
                    rows = await self.db.fetch("""
                        SELECT agent_name, context_key, correlation_id, created_at, updated_at, expires_at, metadata
                        FROM agent_memory 
                        WHERE user_id = $1 AND agent_name = $2
                        AND (expires_at IS NULL OR expires_at > now())
                        ORDER BY updated_at DESC
                    """, user_id, agent_name)
                else:
                    rows = await self.db.fetch("""
                        SELECT agent_name, context_key, correlation_id, created_at, updated_at, expires_at, metadata
                        FROM agent_memory 
                        WHERE user_id = $1
                        AND (expires_at IS NULL OR expires_at > now())
                        ORDER BY updated_at DESC
                    """, user_id)
                
                contexts = []
                for row in rows:
                    contexts.append({
                        "agent_name": row['agent_name'],
                        "context_key": row['context_key'],
                        "correlation_id": row['correlation_id'],
                        "created_at": row['created_at'].isoformat() if row['created_at'] else None,
                        "updated_at": row['updated_at'].isoformat() if row['updated_at'] else None,
                        "expires_at": row['expires_at'].isoformat() if row['expires_at'] else None,
                        "metadata": json.loads(row['metadata']) if row['metadata'] else {}
                    })
                
                span.set_attributes({
                    "memory.contexts_found": len(contexts)
                })
                span.set_status(Status(StatusCode.OK))
                
                return contexts
                
            except Exception as e:
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                self.logger.error(
                    "Failed to list agent contexts",
                    user_id=user_id,
                    agent_name=agent_name,
                    error=str(e),
                    exc_info=True
                )
                return []
    
    async def cleanup_expired(self) -> int:
        with tracer.start_as_current_span("agent_memory_cleanup_expired") as span:
            await self.initialize()
            
            try:
                result = await self.db.execute("""
                    DELETE FROM agent_memory 
                    WHERE expires_at IS NOT NULL AND expires_at <= now()
                """)
                
                span.set_attributes({
                    "memory.cleaned_count": result
                })
                span.set_status(Status(StatusCode.OK))
                
                if result > 0:
                    self.logger.info("Cleaned up expired agent contexts", count=result)
                
                return result
                
            except Exception as e:
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                self.logger.error("Failed to cleanup expired contexts", error=str(e), exc_info=True)
                return 0
    
    async def store_execution_context(
        self,
        user_id: str,
        correlation_id: str,
        context_data: Dict[str, Any],
        ttl: timedelta = timedelta(days=30)
    ) -> bool:
        return await self.store_context(
            user_id=user_id,
            agent_name="intelligent_provision",
            context_key=f"execution:{correlation_id}",
            context_data=context_data,
            correlation_id=correlation_id,
            ttl=ttl,
            metadata={
                "type": "execution_context",
                "stored_at": datetime.now(UTC).isoformat()
            }
        )
    
    async def get_execution_context(
        self,
        user_id: str,
        correlation_id: str
    ) -> Optional[Dict[str, Any]]:
        return await self.get_context(
            user_id=user_id,
            agent_name="intelligent_provision",
            context_key=f"execution:{correlation_id}"
        )


_persistence_instance: AgentMemoryPersistence = None


async def get_agent_memory() -> AgentMemoryPersistence:
    global _persistence_instance
    if _persistence_instance is None:
        _persistence_instance = AgentMemoryPersistence()
    return _persistence_instance
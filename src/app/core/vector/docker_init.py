from __future__ import annotations

import asyncio
import os
from typing import Any, Dict, Optional

from app.core.plugins.manager import PluginManager
from app.core.plugins.base import PluginConfig
from app.core.vector.plugins.vector_plugin import VectorDatabasePlugin
from app.core.logging import get_logger

logger = get_logger(__name__)


async def initialize_vector_for_docker() -> Dict[str, Any]:
    try:
        plugin_manager = PluginManager()
        
        vector_config = PluginConfig(
            enabled=True,
            configuration={
                "provider": os.getenv("VECTOR_PROVIDER", "chroma"),
                "embedding_model": os.getenv("VECTOR_EMBEDDING_MODEL", "text-embedding-3-small"),
                "dimension": int(os.getenv("VECTOR_DIMENSION", "1536")),
                "connection_config": {
                    "host": os.getenv("VECTOR_HOST", "localhost"),
                    "port": int(os.getenv("VECTOR_PORT", "8001"))
                },
                "auto_index_resources": os.getenv("VECTOR_AUTO_INDEX", "true").lower() == "true",
                "cache_ttl_hours": int(os.getenv("VECTOR_CACHE_TTL_HOURS", "24"))
            },
            load_priority=10,
            auto_reload=False
        )
        
        vector_plugin = VectorDatabasePlugin(vector_config)
        
        plugin_manager._registry.register_plugin("vector_database", vector_plugin, vector_config)
        
        initialization_results = await plugin_manager.initialize_all()
        
        logger.info("Vector system initialized for Docker", initialization_results=initialization_results)
        
        return {
            "success": True,
            "plugin_manager": plugin_manager,
            "initialization_results": initialization_results
        }
        
    except Exception as e:
        logger.error("Failed to initialize vector system for Docker", error=str(e), exc_info=True)
        return {
            "success": False,
            "error": str(e),
            "plugin_manager": None
        }


_docker_plugin_manager: Optional[PluginManager] = None


async def get_docker_plugin_manager() -> Optional[PluginManager]:
    global _docker_plugin_manager
    
    if _docker_plugin_manager is None:
        result = await initialize_vector_for_docker()
        if result["success"]:
            _docker_plugin_manager = result["plugin_manager"]
    
    return _docker_plugin_manager
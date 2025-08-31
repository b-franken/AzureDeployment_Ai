from __future__ import annotations

from typing import Any, Dict, List
from datetime import datetime, UTC

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from .base import VectorProvider, VectorQuery, VectorSearchResponse, VectorSearchResult

tracer = trace.get_tracer(__name__)


class ChromaProvider(VectorProvider):
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self._client = None
        self._collections = {}
    
    async def initialize(self) -> None:
        with tracer.start_as_current_span("vectordatabase_initialize") as span:
            try:
                import chromadb
                from chromadb.config import Settings
                
                host = self.config.get("host", "localhost")
                port = self.config.get("port", 8000)
                
                if self.config.get("persistent_path"):
                    self._client = chromadb.PersistentClient(
                        path=self.config["persistent_path"],
                        settings=Settings(anonymized_telemetry=False)
                    )
                else:
                    self._client = chromadb.HttpClient(
                        host=host,
                        port=port,
                        settings=Settings(anonymized_telemetry=False)
                    )
                
                self._client.heartbeat()
                self._initialized = True
                
                span.set_attributes({
                    "vectordatabase.host": host,
                    "vectordatabase.port": port,
                    "vectordatabase.persistent": bool(self.config.get("persistent_path")),
                    "vectordatabase.initialized": True
                })
                span.set_status(Status(StatusCode.OK))
                
            except Exception as e:
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                raise
    
    async def create_collection(self, 
                               collection_name: str, 
                               dimension: int,
                               metadata: Dict[str, Any] | None = None) -> bool:
        with tracer.start_as_current_span("vectordatabase_create_collection") as span:
            span.set_attributes({
                "collection.name": collection_name,
                "collection.dimension": dimension
            })
            
            try:
                collection_metadata = metadata or {}
                collection_metadata["dimension"] = dimension
                collection_metadata["created_at"] = datetime.now(UTC).isoformat()
                
                collection = self._client.create_collection(
                    name=collection_name,
                    metadata=collection_metadata
                )
                
                self._collections[collection_name] = collection
                
                span.set_attributes({
                    "collection.created": True,
                    "collection.metadata_keys": list(collection_metadata.keys())
                })
                span.set_status(Status(StatusCode.OK))
                
                return True
                
            except Exception as e:
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                return False
    
    async def delete_collection(self, collection_name: str) -> bool:
        with tracer.start_as_current_span("vectordatabase_delete_collection") as span:
            span.set_attribute("collection.name", collection_name)
            
            try:
                self._client.delete_collection(name=collection_name)
                self._collections.pop(collection_name, None)
                
                span.set_attribute("collection.deleted", True)
                span.set_status(Status(StatusCode.OK))
                
                return True
                
            except Exception as e:
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                return False
    
    async def list_collections(self) -> List[str]:
        with tracer.start_as_current_span("vectordatabase_list_collections") as span:
            try:
                collections = self._client.list_collections()
                collection_names = [c.name for c in collections]
                
                span.set_attributes({
                    "collections.count": len(collection_names),
                    "collections.names": collection_names
                })
                span.set_status(Status(StatusCode.OK))
                
                return collection_names
                
            except Exception as e:
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                return []
    
    async def upsert_vectors(self,
                           collection_name: str,
                           vectors: List[Dict[str, Any]]) -> bool:
        with tracer.start_as_current_span("vectordatabase_upsert_vectors") as span:
            span.set_attributes({
                "collection.name": collection_name,
                "vectors.count": len(vectors)
            })
            
            try:
                collection = self._get_collection(collection_name)
                
                ids = [v["id"] for v in vectors]
                embeddings = [v["embedding"] for v in vectors]
                documents = [v.get("content", "") for v in vectors]
                metadatas = [self._flatten_metadata(v.get("metadata", {})) for v in vectors]
                
                collection.upsert(
                    ids=ids,
                    embeddings=embeddings,
                    documents=documents,
                    metadatas=metadatas
                )
                
                span.set_attributes({
                    "upsert.success": True,
                    "upsert.vector_count": len(vectors)
                })
                span.set_status(Status(StatusCode.OK))
                
                return True
                
            except Exception as e:
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                # Log the actual ChromaDB error for debugging
                import logging
                logging.error(f"ChromaDB upsert failed: {str(e)}")
                logging.error(f"Vector data sample: {vectors[:1] if vectors else 'None'}")
                logging.error(f"IDs: {ids[:3] if ids else 'None'}")
                logging.error(f"Embeddings count: {len(embeddings) if embeddings else 0}")
                return False
    
    async def delete_vectors(self,
                           collection_name: str, 
                           vector_ids: List[str]) -> bool:
        with tracer.start_as_current_span("vectordatabase_delete_vectors") as span:
            span.set_attributes({
                "collection.name": collection_name,
                "vector_ids.count": len(vector_ids)
            })
            
            try:
                collection = self._get_collection(collection_name)
                collection.delete(ids=vector_ids)
                
                span.set_attributes({
                    "delete.success": True,
                    "delete.count": len(vector_ids)
                })
                span.set_status(Status(StatusCode.OK))
                
                return True
                
            except Exception as e:
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                return False
    
    async def search_similar(self, 
                           collection_name: str,
                           query: VectorQuery) -> VectorSearchResponse:
        start_time = datetime.now(UTC)
        
        with tracer.start_as_current_span("vectordatabase_search_similar") as span:
            span.set_attributes({
                "collection.name": collection_name,
                "query.limit": query.limit,
                "query.threshold": query.threshold,
                "query.has_vector": query.query_vector is not None,
                "query.has_text": bool(query.query_text)
            })
            
            try:
                collection = self._get_collection(collection_name)
                
                where_clause = query.filter_criteria if query.filter_criteria else None
                
                if query.query_vector:
                    results = collection.query(
                        query_embeddings=[query.query_vector],
                        n_results=query.limit,
                        where=where_clause,
                        include=["documents", "metadatas", "distances", "embeddings"] if query.include_metadata else ["documents", "distances"]
                    )
                else:
                    results = collection.query(
                        query_texts=[query.query_text],
                        n_results=query.limit,
                        where=where_clause,
                        include=["documents", "metadatas", "distances", "embeddings"] if query.include_metadata else ["documents", "distances"]
                    )
                
                search_results = []
                if results["ids"] and results["ids"][0]:
                    for i in range(len(results["ids"][0])):
                        score = 1.0 - results["distances"][0][i]  # Convert distance to similarity
                        
                        if score >= query.threshold:
                            result = VectorSearchResult(
                                id=results["ids"][0][i],
                                content=results["documents"][0][i] if results["documents"] else "",
                                score=score,
                                metadata=results["metadatas"][0][i] if results.get("metadatas") else {},
                                embedding=results["embeddings"][0][i] if results.get("embeddings") else None
                            )
                            search_results.append(result)
                
                search_time = (datetime.now(UTC) - start_time).total_seconds() * 1000
                
                response = VectorSearchResponse(
                    query=query,
                    results=search_results,
                    total_found=len(search_results),
                    search_time_ms=search_time,
                    provider="ChromaProvider"
                )
                
                span.set_attributes({
                    "search.results_count": len(search_results),
                    "search.time_ms": search_time,
                    "search.success": True
                })
                span.set_status(Status(StatusCode.OK))
                
                return response
                
            except Exception as e:
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                
                search_time = (datetime.now(UTC) - start_time).total_seconds() * 1000
                return VectorSearchResponse(
                    query=query,
                    results=[],
                    total_found=0,
                    search_time_ms=search_time,
                    provider="ChromaProvider"
                )
    
    async def get_vector_by_id(self,
                             collection_name: str,
                             vector_id: str) -> VectorSearchResult | None:
        with tracer.start_as_current_span("vectordatabase_get_vector_by_id") as span:
            span.set_attributes({
                "collection.name": collection_name,
                "vector.id": vector_id
            })
            
            try:
                collection = self._get_collection(collection_name)
                
                result = collection.get(
                    ids=[vector_id],
                    include=["documents", "metadatas", "embeddings"]
                )
                
                if result["ids"] and result["ids"][0]:
                    vector_result = VectorSearchResult(
                        id=result["ids"][0],
                        content=result["documents"][0] if result["documents"] else "",
                        score=1.0,
                        metadata=result["metadatas"][0] if result["metadatas"] else {},
                        embedding=result["embeddings"][0] if result["embeddings"] else None
                    )
                    
                    span.set_attribute("vector.found", True)
                    span.set_status(Status(StatusCode.OK))
                    
                    return vector_result
                else:
                    span.set_attribute("vector.found", False)
                    span.set_status(Status(StatusCode.OK))
                    return None
                    
            except Exception as e:
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                return None
    
    def _get_collection(self, collection_name: str, auto_create: bool = True):
        if collection_name not in self._collections:
            try:
                self._collections[collection_name] = self._client.get_collection(
                    name=collection_name
                )
            except Exception as e:
                if auto_create:
                    try:
                        # Create collection without embedding function to use our custom embeddings
                        self._collections[collection_name] = self._client.create_collection(
                            name=collection_name,
                            embedding_function=None,  # Use manual embeddings
                            metadata={
                                "dimension": 1536,
                                "created_at": datetime.now(UTC).isoformat(),
                                "auto_created": True
                            }
                        )
                    except Exception as create_error:
                        raise ValueError(f"Collection {collection_name} not found and auto-creation failed: {str(create_error)}") from e
                else:
                    raise ValueError(f"Collection {collection_name} not found") from e
        
        return self._collections[collection_name]
    
    def _flatten_metadata(self, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """Flatten complex metadata structures for ChromaDB compatibility"""
        flattened = {}
        
        for key, value in metadata.items():
            if isinstance(value, (str, int, float, bool)) or value is None:
                flattened[key] = value
            elif isinstance(value, dict):
                if not value:  # empty dict
                    flattened[f"{key}_empty"] = True
                else:
                    # Flatten dict as JSON string
                    import json
                    flattened[f"{key}_json"] = json.dumps(value)
            elif isinstance(value, list):
                if not value:  # empty list
                    flattened[f"{key}_empty"] = True
                else:
                    # Join list items as string
                    flattened[f"{key}_list"] = str(value)
            else:
                # Convert other types to string
                flattened[f"{key}_str"] = str(value)
        
        return flattened
    
    async def get_stats(self, collection_name: str) -> Dict[str, Any]:
        with tracer.start_as_current_span("vectordatabase_get_stats") as span:
            span.set_attribute("collection.name", collection_name)
            
            try:
                collection = self._get_collection(collection_name)
                count = collection.count()
                
                stats = {
                    "provider": "ChromaProvider",
                    "collection": collection_name,
                    "vector_count": count,
                    "status": "healthy" if self._client else "unhealthy",
                    "timestamp": datetime.now(UTC).isoformat()
                }
                
                span.set_attributes({
                    "stats.vector_count": count,
                    "stats.status": stats["status"]
                })
                span.set_status(Status(StatusCode.OK))
                
                return stats
                
            except Exception as e:
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                return {
                    "provider": "ChromaProvider",
                    "collection": collection_name,
                    "error": str(e),
                    "status": "error",
                    "timestamp": datetime.now(UTC).isoformat()
                }
    
    async def similarity_search(self, embedding: List[float], limit: int = 10) -> List[Dict[str, Any]]:
        with tracer.start_as_current_span("vectordatabase_similarity_search") as span:
            span.set_attributes({
                "search.embedding_dim": len(embedding),
                "search.limit": limit
            })
            
            try:
                results = []
                for collection_name in self._collections:
                    collection = self._collections[collection_name]
                    query_results = collection.query(
                        query_embeddings=[embedding],
                        n_results=limit,
                        include=["documents", "metadatas", "distances"]
                    )
                    
                    if query_results["ids"] and query_results["ids"][0]:
                        for i in range(len(query_results["ids"][0])):
                            score = 1.0 - query_results["distances"][0][i]
                            result = {
                                "id": query_results["ids"][0][i],
                                "score": score,
                                "content": query_results["documents"][0][i] if query_results["documents"] else "",
                                "metadata": query_results["metadatas"][0][i] if query_results["metadatas"] else {}
                            }
                            results.append(result)
                
                results.sort(key=lambda x: x["score"], reverse=True)
                results = results[:limit]
                
                span.set_attribute("search.results_count", len(results))
                span.set_status(Status(StatusCode.OK))
                
                return results
                
            except Exception as e:
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                return []
    
    async def cleanup_old_vectors(self, max_age) -> int:
        with tracer.start_as_current_span("vectordatabase_cleanup_old_vectors") as span:
            span.set_attribute("cleanup.max_age", str(max_age))
            
            try:
                cleaned_count = 0
                cutoff_time = datetime.now(UTC) - max_age
                
                for collection_name in list(self._collections.keys()):
                    collection = self._collections[collection_name]
                    
                    all_vectors = collection.get(include=["metadatas"])
                    vectors_to_delete = []
                    
                    if all_vectors["ids"]:
                        for i, vector_id in enumerate(all_vectors["ids"]):
                            metadata = all_vectors["metadatas"][i] if all_vectors["metadatas"] else {}
                            indexed_at_str = metadata.get("indexed_at")
                            
                            if indexed_at_str:
                                try:
                                    indexed_at = datetime.fromisoformat(indexed_at_str.replace('Z', '+00:00'))
                                    if indexed_at < cutoff_time:
                                        vectors_to_delete.append(vector_id)
                                except (ValueError, TypeError):
                                    continue
                    
                    if vectors_to_delete:
                        collection.delete(ids=vectors_to_delete)
                        cleaned_count += len(vectors_to_delete)
                
                span.set_attribute("cleanup.cleaned_count", cleaned_count)
                span.set_status(Status(StatusCode.OK))
                
                return cleaned_count
                
            except Exception as e:
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                return 0
    
    async def health_check(self) -> Dict[str, Any]:
        with tracer.start_as_current_span("vectordatabase_health_check") as span:
            try:
                if self._client:
                    self._client.heartbeat()
                    status = "healthy"
                else:
                    status = "unhealthy"
                
                health_data = {
                    "provider": "ChromaProvider",
                    "status": status,
                    "collections_count": len(self._collections),
                    "initialized": self._initialized,
                    "timestamp": datetime.now(UTC).isoformat()
                }
                
                span.set_attributes({
                    "health.status": status,
                    "health.collections_count": len(self._collections),
                    "health.initialized": self._initialized
                })
                span.set_status(Status(StatusCode.OK))
                
                return health_data
                
            except Exception as e:
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                return {
                    "provider": "ChromaProvider",
                    "status": "unhealthy",
                    "error": str(e),
                    "timestamp": datetime.now(UTC).isoformat()
                }
    
    async def shutdown(self) -> None:
        with tracer.start_as_current_span("vectordatabase_shutdown") as span:
            try:
                self._collections.clear()
                self._client = None
                self._initialized = False
                
                span.set_status(Status(StatusCode.OK))
                
            except Exception as e:
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                raise
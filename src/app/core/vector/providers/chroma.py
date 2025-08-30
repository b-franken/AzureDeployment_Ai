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
        with tracer.start_as_current_span("chroma_initialize") as span:
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
                
                await self._client.heartbeat()
                self._initialized = True
                
                span.set_attributes({
                    "chroma.host": host,
                    "chroma.port": port,
                    "chroma.persistent": bool(self.config.get("persistent_path")),
                    "chroma.initialized": True
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
        with tracer.start_as_current_span("chroma_create_collection") as span:
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
        with tracer.start_as_current_span("chroma_delete_collection") as span:
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
        with tracer.start_as_current_span("chroma_list_collections") as span:
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
        with tracer.start_as_current_span("chroma_upsert_vectors") as span:
            span.set_attributes({
                "collection.name": collection_name,
                "vectors.count": len(vectors)
            })
            
            try:
                collection = self._get_collection(collection_name)
                
                ids = [v["id"] for v in vectors]
                embeddings = [v["embedding"] for v in vectors]
                documents = [v.get("content", "") for v in vectors]
                metadatas = [v.get("metadata", {}) for v in vectors]
                
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
                return False
    
    async def delete_vectors(self,
                           collection_name: str, 
                           vector_ids: List[str]) -> bool:
        with tracer.start_as_current_span("chroma_delete_vectors") as span:
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
        
        with tracer.start_as_current_span("chroma_search_similar") as span:
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
        with tracer.start_as_current_span("chroma_get_vector_by_id") as span:
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
    
    def _get_collection(self, collection_name: str):
        if collection_name not in self._collections:
            try:
                self._collections[collection_name] = self._client.get_collection(
                    name=collection_name
                )
            except Exception:
                raise ValueError(f"Collection {collection_name} not found")
        
        return self._collections[collection_name]
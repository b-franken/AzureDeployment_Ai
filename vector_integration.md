# Vector Database Integration

This document describes the comprehensive vector database integration for the Azure Deployment AI system, providing semantic search, RAG capabilities, and intelligent context-aware provisioning.

## Overview

The vector integration enhances the AI system with:

- **Semantic Search**: Find similar deployments, configurations, and conversations
- **Context-Aware Provisioning**: Learn from historical deployment patterns
- **Intelligent Recommendations**: Suggest best practices based on past experiences
- **Pattern Analysis**: Identify deployment trends and optimizations
- **RAG Capabilities**: Retrieve relevant context for improved AI responses

## Architecture

```
┌─────────────────────┐    ┌──────────────────────┐    ┌─────────────────────┐
│   Frontend (React)  │    │   API Server         │    │   ChromaDB          │
│                     │    │                      │    │   (Vector Store)    │
│ • Chat Interface    │────│ • Intelligent        │────│                     │
│ • Preview/Deploy    │    │   Provision Tool     │    │ • Embeddings        │
│ • Cost Analysis     │    │ • Vector Enhanced    │    │ • Similarity Search │
└─────────────────────┘    │   Parser             │    │ • Collections       │
                           │ • Plugin Manager     │    └─────────────────────┘
┌─────────────────────┐    │                      │    
│   MCP Server        │────│ • Vector Plugin      │    ┌─────────────────────┐
│                     │    │ • Memory Layer       │    │   PostgreSQL        │
│ • Vector Tools      │    │ • AI Agents          │    │   (Memory Store)    │
│ • Intelligence API  │    └──────────────────────┘    │                     │
│ • Analytics         │                               │ • Agent Context     │
└─────────────────────┘    ┌──────────────────────┐    │ • Execution History │
                           │   Observability      │    │ • User Sessions     │
                           │                      │    └─────────────────────┘
                           │ • OpenTelemetry      │
                           │ • Application Insights
                           │ • Distributed Tracing
                           └──────────────────────┘
```

## Components

### 1. Vector Database Plugin (`src/app/core/vector/plugins/vector_plugin.py`)

The main plugin that provides vector database capabilities:

- **Initialization**: Sets up vector providers (ChromaDB, Pinecone, Azure Search)
- **Operations**: Semantic search, content indexing, similarity search
- **Configuration**: Embedding models, dimensions, connection settings
- **Observability**: Full telemetry and Application Insights integration

Key features:
- Configurable vector providers
- Embedding caching with TTL
- Automatic resource indexing
- Context cleanup and maintenance

### 2. Vector-Enhanced Provisioning (`src/app/tools/azure/vector_enhanced_provision.py`)

Enhances Azure provisioning with historical context:

- **Context Retrieval**: Gets similar deployments and configurations
- **Enhanced Planning**: Uses historical patterns for better decisions
- **Risk Assessment**: Analyzes failure patterns from similar deployments
- **Outcome Indexing**: Stores deployment results for future learning

### 3. Vector-Enhanced AI Agents (`src/app/ai/agents/vector_enhanced_agent.py`)

AI agents with semantic memory capabilities:

- **Context-Aware Responses**: Uses historical conversations and deployments
- **Pattern Learning**: Identifies successful deployment patterns
- **Recommendation Generation**: Suggests optimizations based on experience
- **Memory Integration**: Stores and retrieves agent interactions

### 4. Vector-Enhanced NLU Parser (`src/app/ai/nlu/vector_enhanced_parser.py`)

Natural Language Understanding with semantic context:

- **Similarity-Based Enhancement**: Improves parsing confidence with similar requests
- **Parameter Enhancement**: Suggests parameters from successful deployments
- **Confidence Boosting**: Increases accuracy using historical patterns
- **Context Suggestions**: Provides recommendations based on similar requests

### 5. MCP Vector Intelligence Tools (`src/app/mcp/tools/vector_intelligence.py`)

Model Context Protocol tools for vector operations:

- **Semantic Search**: Search across deployment history and documentation
- **Content Indexing**: Index new deployments and configurations
- **Deployment Recommendations**: AI-powered suggestions
- **Pattern Analysis**: Analyze deployment trends and success rates
- **Similarity Search**: Find similar configurations and outcomes

## Configuration

### Environment Variables

```bash
# Vector Database Configuration
VECTOR_PROVIDER=chroma                    # chroma, pinecone, azure_search
VECTOR_HOST=chroma                        # ChromaDB host
VECTOR_PORT=8001                          # ChromaDB port
VECTOR_EMBEDDING_MODEL=text-embedding-3-small  # OpenAI embedding model
VECTOR_DIMENSION=1536                     # Embedding dimensions
VECTOR_AUTO_INDEX=true                    # Auto-index resources
VECTOR_CACHE_TTL_HOURS=24                 # Embedding cache TTL

# Optional: Pinecone Configuration
PINECONE_API_KEY=your-api-key
PINECONE_ENVIRONMENT=your-environment
PINECONE_INDEX_NAME=azure-deployments

# Optional: Azure Search Configuration
AZURE_SEARCH_SERVICE_NAME=your-service
AZURE_SEARCH_API_KEY=your-key
AZURE_SEARCH_INDEX_NAME=azure-deployments
```

### Docker Compose

The system includes ChromaDB service:

```yaml
chroma:
  image: chromadb/chroma:latest
  container_name: devops-ai-chroma
  environment:
    - CHROMA_SERVER_HOST=0.0.0.0
    - CHROMA_SERVER_HTTP_PORT=8001
    - ALLOW_RESET=TRUE
  volumes:
    - chroma_data:/chroma/chroma
  ports:
    - "8001:8001"
  healthcheck:
    test: ["CMD", "curl", "-f", "http://localhost:8001/api/v1/heartbeat"]
    interval: 10s
    timeout: 5s
    retries: 20
```

## Usage

### 1. Enhanced Intelligent Provisioning

The system automatically uses vector enhancement when available:

```python
# The IntelligentAzureProvision tool automatically initializes vector capabilities
from app.tools.azure.intelligent_provision import IntelligentAzureProvision

tool = IntelligentAzureProvision()
result = await tool.run(
    request="Deploy a web app with SQL database",
    user_id="user123",
    environment="prod",
    dry_run=True
)
```

### 2. MCP Vector Tools

Available through the MCP server:

```python
# Semantic search
result = await mcp.call_tool(
    "semantic_search",
    {
        "query": "web app with database deployment",
        "limit": 10,
        "threshold": 0.7,
        "user_id": "user123"
    }
)

# Get deployment recommendations
recommendations = await mcp.call_tool(
    "get_deployment_recommendations",
    {
        "current_deployment": "Create AKS cluster with monitoring",
        "include_historical": True,
        "max_recommendations": 5
    }
)

# Index content
await mcp.call_tool(
    "index_content",
    {
        "content": "Successful AKS deployment with Application Gateway",
        "resource_type": "aks_deployment",
        "metadata": {"success": True, "cost": 150.50}
    }
)
```

### 3. Direct Vector Operations

For advanced use cases:

```python
from app.core.vector.docker_init import get_docker_plugin_manager
from app.core.plugins.base import PluginContext

# Get plugin manager
plugin_manager = await get_docker_plugin_manager()

# Execute vector operations
context = PluginContext(
    plugin_name="vector_database",
    correlation_id="search123",
    execution_context={
        "operation": "semantic_search",
        "query": "kubernetes deployment patterns",
        "limit": 5
    }
)

result = await plugin_manager.execute_plugin("vector_database", context)
```

## Observability

### Application Insights Events

The vector system generates comprehensive telemetry:

- **vector_plugin_initialized**: Plugin startup
- **vector_enhanced_provision_completed**: Enhanced provisioning
- **vector_enhanced_parsing_completed**: NLU parsing with context
- **mcp_vector_tool_executed**: MCP tool usage
- **vector_operation_completed**: Generic vector operations

### Distributed Tracing

All vector operations are traced with OpenTelemetry:

```
provision_orchestration
├── vector_enhanced_provision
│   ├── get_provisioning_context
│   │   └── semantic_search
│   ├── create_enhanced_context
│   └── index_provisioning_outcome
└── strategy_execution
```

### Custom Metrics

Track vector system performance:

- Similarity search latency
- Context retrieval success rates
- Embedding cache hit rates
- Pattern analysis accuracy
- Recommendation acceptance rates

## Data Flow

### 1. Deployment with Vector Enhancement

```
User Request → NLU Parser (+ Vector Context) → Enhanced Parameters
    ↓
Intelligent Provision Tool → Get Historical Context → ChromaDB
    ↓
Provisioning Orchestrator → AVM/SDK Strategies
    ↓
Deployment Result → Index Outcome → ChromaDB + Memory
```

### 2. MCP Vector Intelligence

```
MCP Client → Vector Intelligence Tool → Plugin Manager
    ↓
Vector Plugin → ChromaDB → Semantic Search Results
    ↓
Response with Context → Application Insights Telemetry
```

### 3. AI Agent Context

```
Agent Request → Vector Enhanced Agent → Get Relevant Context
    ↓
Historical Patterns → Enhanced Response Generation
    ↓
Store Interaction → Memory Layer + Vector Index
```

## Performance Considerations

### Embedding Caching

- TTL-based cache for embeddings (default 24 hours)
- Reduces API calls to embedding providers
- Improves response times for repeated queries

### Similarity Thresholds

- Default threshold: 0.7 for semantic search
- Higher thresholds (0.8+) for critical operations
- Lower thresholds (0.6) for exploratory search

### Batch Operations

- Batch embedding generation for multiple documents
- Async processing for non-blocking operations
- Background indexing of deployment outcomes

## Security

### Access Control

- User-scoped searches when user_id is provided
- Metadata filtering for sensitive information
- Audit logging for all vector operations

### Data Privacy

- No sensitive credentials stored in vectors
- Configurable data retention policies
- Option to exclude specific content from indexing

## Monitoring

### Health Checks

```bash
# ChromaDB health
curl http://localhost:8001/api/v1/heartbeat

# Plugin status
curl http://localhost:8080/api/v1/health
```

### Key Metrics

- Vector database connection status
- Embedding generation latency
- Search result relevance scores
- Context cache hit rates
- Plugin initialization success rates

## Troubleshooting

### Common Issues

1. **ChromaDB Connection Failed**
   - Verify ChromaDB is running: `docker ps | grep chroma`
   - Check network connectivity: `docker network inspect devops-ai-net`
   - Review logs: `docker logs devops-ai-chroma`

2. **Embedding API Limits**
   - Monitor OpenAI API usage
   - Implement rate limiting in production
   - Consider local embedding models for high volume

3. **Low Similarity Scores**
   - Adjust similarity thresholds
   - Verify embedding model consistency
   - Review content quality and indexing

4. **Memory Growth**
   - Monitor embedding cache size
   - Configure appropriate TTL values
   - Implement cleanup routines

### Debug Commands

```bash
# Check vector plugin status
docker exec devops-ai-api python -c "
from app.core.vector.docker_init import get_docker_plugin_manager
import asyncio
pm = asyncio.run(get_docker_plugin_manager())
print(pm.get_manager_stats() if pm else 'Not initialized')
"

# Test ChromaDB connection
curl -X GET http://localhost:8001/api/v1/collections

# View Application Insights traces
# Search for "vector" in Azure portal Application Insights
```

## Future Enhancements

### Planned Features

- **Multi-modal Embeddings**: Support for images, diagrams, and code
- **Federated Search**: Search across multiple vector databases
- **Real-time Learning**: Continuous model fine-tuning
- **Advanced Analytics**: Deployment success prediction
- **Integration APIs**: External system integration

### Performance Optimizations

- **Vector Quantization**: Reduce storage requirements
- **Approximate Search**: Faster similarity search with HNSW
- **Distributed Indexing**: Scale across multiple nodes
- **GPU Acceleration**: Hardware-optimized embeddings

## Contributing

When extending vector functionality:

1. Add comprehensive telemetry and logging
2. Include proper error handling and fallbacks
3. Write tests for vector operations
4. Update documentation and configuration examples
5. Consider performance implications and caching strategies

---

The vector database integration provides a foundation for intelligent, context-aware Azure deployments that learn and improve from experience. This 2025+ AI engineering approach enables sophisticated pattern recognition, recommendation systems, and automated optimization based on historical deployment data.
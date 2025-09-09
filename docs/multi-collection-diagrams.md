# Multi-Collection RAG System - Architectural Diagrams

## 1. System Overview

```mermaid
graph TB
    subgraph "Client Layer"
        UI[User Interface/Claude]
        CLI[CLI Tools]
    end
    
    subgraph "MCP API Layer"
        Tools[MCP Tools]
        Resources[MCP Resources]
    end
    
    subgraph "Core Services"
        CS[Collection Selector]
        CR[Collection Registry]
        CM[Collection Manager]
        QP[Query Processor]
    end
    
    subgraph "Data Layer"
        ChromaDB[Chroma Vector DB]
        Config[Configuration Files]
        Cache[Embedding Cache]
    end
    
    UI --> Tools
    CLI --> Tools
    Tools --> CS
    Tools --> CR
    Tools --> QP
    CS --> CR
    QP --> CM
    CM --> ChromaDB
    CR --> Config
    CS --> Cache
    
    Resources --> CM
    Resources --> ChromaDB
```

## 2. Collection Selection Flow

```mermaid
sequenceDiagram
    participant User
    participant MCP_API
    participant Selector
    participant Registry
    participant Collection
    
    User->>MCP_API: search(query)
    MCP_API->>Selector: select_collection(query)
    Selector->>Selector: analyze_query()
    
    alt Explicit Collection Reference
        Selector->>Registry: get_collection(explicit_id)
    else Auto-Selection
        Selector->>Selector: keyword_match()
        Selector->>Selector: semantic_match()
        Selector->>Selector: combine_scores()
    end
    
    Selector->>Registry: get_collection(selected_id)
    Registry->>Collection: lazy_load()
    Registry-->>Selector: collection_instance
    Selector-->>MCP_API: CollectionMatch
    
    MCP_API->>Collection: search(query, k)
    Collection->>Collection: query_chroma()
    Collection-->>MCP_API: search_results
    MCP_API-->>User: formatted_results
```

## 3. Data Ingestion Pipeline

```mermaid
graph LR
    subgraph "Input"
        URLs[Web URLs]
        Config[Collection Config]
    end
    
    subgraph "Processing"
        Crawler[Web Crawler]
        Extractor[Text Extractor]
        Chunker[Text Chunker]
        Embedder[Embedding Generator]
    end
    
    subgraph "Storage"
        Chroma[Chroma Collection]
        Metadata[Metadata Store]
    end
    
    URLs --> Crawler
    Config --> Crawler
    Crawler --> Extractor
    Extractor --> Chunker
    Chunker --> Embedder
    Embedder --> Chroma
    Embedder --> Metadata
    
    Config --> Chunker
    Config --> Embedder
```

## 4. Collection Registry Architecture

```mermaid
classDiagram
    class CollectionRegistry {
        -config_path: str
        -collections: Dict[str, CollectionMetadata]
        -_collection_instances: Dict[str, Collection]
        +load_registry()
        +get_collection(id: str): Collection
        +list_collections(): List[CollectionMetadata]
        +refresh()
        +discover_collections()
    }
    
    class CollectionMetadata {
        +id: str
        +name: str
        +description: str
        +domain: str
        +tags: List[str]
        +config: CollectionConfig
        +sources: SourceConfig
        +metadata: Dict
    }
    
    class Collection {
        -metadata: CollectionMetadata
        -client: ChromaClient
        -emb_fn: EmbeddingFunction
        -chroma_collection: ChromaCollection
        +search(query: str, k: int): List[Dict]
        +has_data(): bool
        +get_document_count(): int
        +peek(limit: int): List[Dict]
    }
    
    class CollectionConfig {
        +chunk_chars: int
        +chunk_overlap: int
        +embedding_provider: str
        +embedding_model: str
        +max_pages: int
        +concurrency: int
    }
    
    class SourceConfig {
        +base_urls: List[str]
        +allow_patterns: List[str]
        +deny_patterns: List[str]
    }
    
    CollectionRegistry "1" --> "*" CollectionMetadata
    CollectionRegistry "1" --> "*" Collection
    Collection "1" --> "1" CollectionMetadata
    CollectionMetadata "1" --> "1" CollectionConfig
    CollectionMetadata "1" --> "1" SourceConfig
```

## 5. Query Processing Flow

```mermaid
stateDiagram-v2
    [*] --> QueryReceived
    QueryReceived --> CheckExplicitRef
    
    CheckExplicitRef --> ExplicitFound: Has @collection
    CheckExplicitRef --> AutoSelect: No explicit ref
    
    ExplicitFound --> ValidateCollection
    ValidateCollection --> CollectionExists: Valid
    ValidateCollection --> NoCollection: Invalid
    
    AutoSelect --> KeywordAnalysis
    KeywordAnalysis --> SemanticAnalysis
    SemanticAnalysis --> ScoreCombination
    ScoreCombination --> ThresholdCheck
    
    ThresholdCheck --> CollectionSelected: Above threshold
    ThresholdCheck --> NoCollection: Below threshold
    
    CollectionExists --> ExecuteSearch
    CollectionSelected --> ExecuteSearch
    NoCollection --> ReturnEmpty
    
    ExecuteSearch --> FormatResults
    FormatResults --> [*]
    ReturnEmpty --> [*]
```

## 6. Component Interaction Matrix

```mermaid
graph TD
    subgraph "Component Interactions"
        A[MCP Server] -.->|uses| B[Collection Registry]
        A -.->|uses| C[Collection Selector]
        A -.->|uses| D[Query Processor]
        
        B -.->|manages| E[Collections]
        B -.->|reads| F[Config Files]
        
        C -.->|queries| B
        C -.->|uses| G[Embedding Cache]
        C -.->|computes| H[Similarity Scores]
        
        D -.->|uses| E
        D -.->|formats| I[Search Results]
        
        E -.->|connects| J[Chroma DB]
        E -.->|uses| K[Embedding Functions]
        
        L[Ingest Pipeline] -.->|writes| J
        L -.->|uses| F
        L -.->|uses| K
    end
    
    style A fill:#f9f,stroke:#333,stroke-width:4px
    style B fill:#bbf,stroke:#333,stroke-width:2px
    style C fill:#bbf,stroke:#333,stroke-width:2px
    style D fill:#bbf,stroke:#333,stroke-width:2px
    style J fill:#ff9,stroke:#333,stroke-width:2px
```

## 7. State Management

```mermaid
stateDiagram-v2
    [*] --> Uninitialized
    
    Uninitialized --> Loading: initialize()
    Loading --> ConfigLoaded: load_config()
    ConfigLoaded --> RegistryBuilt: build_registry()
    RegistryBuilt --> Ready: validate()
    
    Ready --> Processing: receive_request()
    Processing --> Ready: complete_request()
    
    Ready --> Refreshing: refresh_signal()
    Refreshing --> ConfigLoaded: reload_config()
    
    Ready --> [*]: shutdown()
    
    state Processing {
        [*] --> SelectingCollection
        SelectingCollection --> CollectionSelected
        CollectionSelected --> Searching
        Searching --> ResultsFound
        ResultsFound --> [*]
    }
```

## 8. Deployment Architecture

```mermaid
graph TB
    subgraph "Development Environment"
        DevMCP[MCP Server Dev]
        DevChroma[Local Chroma]
        DevConfig[Local Configs]
    end
    
    subgraph "Production Environment"
        ProdMCP[MCP Server Prod]
        ProdChroma[Chroma Cluster]
        ProdConfig[Config Store]
        ProdCache[Redis Cache]
    end
    
    subgraph "Shared Services"
        Embeddings[Embedding Service]
        Monitoring[Monitoring/Logging]
    end
    
    DevMCP --> DevChroma
    DevMCP --> DevConfig
    DevMCP --> Embeddings
    
    ProdMCP --> ProdChroma
    ProdMCP --> ProdConfig
    ProdMCP --> ProdCache
    ProdMCP --> Embeddings
    
    DevMCP --> Monitoring
    ProdMCP --> Monitoring
```

## 9. Error Handling Flow

```mermaid
flowchart TD
    Start([Request Received]) --> Validate{Valid Request?}
    Validate -->|No| ReturnError1[Return 400 Error]
    Validate -->|Yes| SelectCol{Select Collection}
    
    SelectCol -->|No Match| CheckDefault{Has Default?}
    CheckDefault -->|No| ReturnNoCol[Return No Collection]
    CheckDefault -->|Yes| UseDefault[Use Default Collection]
    
    SelectCol -->|Match Found| LoadCol{Load Collection}
    UseDefault --> LoadCol
    
    LoadCol -->|Failed| ReturnError2[Return 500 Error]
    LoadCol -->|Success| Search{Execute Search}
    
    Search -->|Error| HandleSearchError{Retry?}
    HandleSearchError -->|Yes| Search
    HandleSearchError -->|No| ReturnError3[Return Search Error]
    
    Search -->|Success| Format[Format Results]
    Format --> ReturnSuccess([Return Results])
    
    ReturnError1 --> End([End])
    ReturnNoCol --> End
    ReturnError2 --> End
    ReturnError3 --> End
    ReturnSuccess --> End
```

## 10. Caching Strategy

```mermaid
graph LR
    subgraph "Cache Layers"
        L1[Query Cache<br/>TTL: 5min]
        L2[Embedding Cache<br/>TTL: 1hr]
        L3[Collection Metadata<br/>TTL: 10min]
    end
    
    subgraph "Cache Operations"
        Check[Check Cache]
        Hit[Cache Hit]
        Miss[Cache Miss]
        Update[Update Cache]
    end
    
    Query --> Check
    Check --> Hit
    Check --> Miss
    Hit --> Return
    Miss --> Compute
    Compute --> Update
    Update --> Return
    
    L1 -.-> Check
    L2 -.-> Check
    L3 -.-> Check

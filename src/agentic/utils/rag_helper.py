from pathlib import Path
from datetime import datetime
import hashlib
from typing import Dict, Any, List, Optional

from weaviate import WeaviateClient
from weaviate.embedded import EmbeddedOptions
from weaviate.classes.config import (
    DataType,
    Property,
    Configure,
    VectorDistances
)
from weaviate.classes.query import Filter
from chonkie import SemanticChunker
from fastembed import TextEmbedding
from rich.console import Console

from agentic.utils.file_reader import get_last_path_component
from agentic.utils.fingerprint import generate_fingerprint

def init_weaviate() -> WeaviateClient:
    """Initialize and return Weaviate client"""
    client = WeaviateClient(
        embedded_options=EmbeddedOptions(
            persistence_data_path=str(Path.home() / ".cache/weaviate"),
            additional_env_vars={"LOG_LEVEL": "error"}
        )
    )
    client.connect()
    return client

def create_collection(
    client: WeaviateClient,
    index_name: str,
    distance_metric: VectorDistances = VectorDistances.COSINE
) -> None:
    """Create Weaviate collection with standard schema"""
    if not client.collections.exists(index_name):
        client.collections.create(
            name=index_name,
            properties=[
                Property(name="content", data_type=DataType.TEXT),
                Property(name="document_id", data_type=DataType.TEXT,
                        index_filterable=True),
                Property(name="chunk_index", data_type=DataType.INT,
                        index_filterable=True,
                        index_range_filter=True),
                Property(name="filename", data_type=DataType.TEXT,
                        index_filterable=True),
                Property(name="timestamp", data_type=DataType.DATE,
                        index_filterable=True),
                Property(name="mime_type", data_type=DataType.TEXT,
                        index_filterable=True),
                Property(name="source_url", data_type=DataType.TEXT,
                        index_filterable=True),
                Property(name="summary", data_type=DataType.TEXT,
                        index_searchable=True,
                        index_filterable=True),
                Property(name="fingerprint", data_type=DataType.TEXT,
                        index_filterable=True),
            ],
            vectorizer_config=Configure.Vectorizer.none(),
            vector_index_config=Configure.VectorIndex.hnsw(
                distance_metric=distance_metric
            )
        )

def prepare_document_metadata(
    file_path: str,
    text: str,
    mime_type: str,
    model: str
) -> Dict[str, Any]:
    """Prepare document metadata including fingerprint and summary"""
    is_url = file_path.startswith(("http://", "https://"))
    fingerprint = generate_fingerprint(text)
    
    metadata = {
        "filename": Path(file_path).name if not is_url else get_last_path_component(file_path),
        "timestamp": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "mime_type": mime_type,
        "source_url": file_path if is_url else "None",
        "fingerprint": fingerprint
    }
    
    # Generate document ID from filename
    metadata["document_id"] = hashlib.sha256(
        metadata["filename"].encode()
    ).hexdigest()
    
    return metadata

def check_document_exists(
    collection: Any,
    document_id: str,
    fingerprint: str
) -> tuple[bool, str]:
    """Check if document exists and return status"""
    existing_docs = collection.query.fetch_objects(
        limit=1,
        filters=Filter.by_property("document_id").equal(document_id)
    )
    
    if existing_docs.objects:
        existing_fp = existing_docs.objects[0].properties["fingerprint"]
        if existing_fp == fingerprint:
            return True, "unchanged"
        return True, "changed"
    
    existing_content = collection.query.fetch_objects(
        limit=1,
        filters=Filter.by_property("fingerprint").equal(fingerprint)
    )
    if existing_content.objects:
        return True, "duplicate"
        
    return False, "new"

def init_embedding_model(model_name: str) -> TextEmbedding:
    """Initialize the embedding model"""
    return TextEmbedding(model_name=model_name)

def init_chunker(threshold: float, delimiters: str) -> SemanticChunker:
    """Initialize the semantic chunker"""
    return SemanticChunker(
        threshold=threshold,
        delim=delimiters.split(",")
    )

def delete_document_from_index(
    collection: Any,
    document_id: str,
    filename: str
) -> int:
    """Delete document and its chunks from index, return number of deleted chunks"""
    # Get count before deletion for accurate reporting
    original_count = collection.aggregate.over_all(
        filters=Filter.by_property("document_id").equal(document_id),
        total_count=True
    ).total_count
    
    result = collection.data.delete_many(
        where=Filter.by_property("document_id").equal(document_id)
    )
    
    # Verify deletion count matches
    if result.successful != original_count:
        raise RuntimeError(
            f"Deleted {result.successful} chunks but expected {original_count}"
        )
    
    return result.successful

def check_document_in_index(
    collection: Any,
    document_id: str
) -> bool:
    """Check if document exists in index"""
    existing = collection.query.fetch_objects(
        limit=1,
        filters=Filter.by_property("document_id").equal(document_id)
    )
    return bool(existing.objects)

def get_document_id_from_path(file_path: str) -> tuple[str, str]:
    """Generate document ID from file path, return (document_id, filename)"""
    is_url = file_path.startswith(("http://", "https://"))
    filename = Path(file_path).name if not is_url else get_last_path_component(file_path)
    document_id = hashlib.sha256(filename.encode()).hexdigest()
    return document_id, filename

def list_collections(client: WeaviateClient) -> List[str]:
    """List all available indexes/collections"""
    return [col for col in client.collections.list_all()]

def rename_collection(
    client: WeaviateClient,
    source_name: str,
    target_name: str,
    overwrite: bool = False
) -> bool:
    """Rename a Weaviate collection by creating copy and deleting original"""
    # Check if source exists
    if not client.collections.exists(source_name):
        return False
    
    if client.collections.exists(target_name):
        if not overwrite:
            return False
        # Delete existing target collection if overwrite is enabled
        client.collections.delete(target_name)
    
    source_col = client.collections.get(source_name)
    create_collection(client, target_name)
    target_col = client.collections.get(target_name)
    
    # Copy all objects with vectors
    with target_col.batch.dynamic() as batch:
        for obj in source_col.iterator(include_vector=True):
            batch.add_object(
                properties=obj.properties,
                vector=obj.vector["default"]
            )
    
    # Delete original after successful copy
    client.collections.delete(source_name)
    return True

def list_documents_in_collection(collection: Any) -> List[Dict]:
    """List all unique documents in a collection with basic metadata"""
    result = collection.query.fetch_objects(
        limit=1000,
        return_properties=["document_id", "filename", "timestamp", "fingerprint"],
        include_vector=False
    )
    
    seen = set()
    documents = []
    for obj in result.objects:
        if obj.properties["document_id"] not in seen:
            seen.add(obj.properties["document_id"])
            chunk_count = collection.aggregate.over_all(
                filters=Filter.by_property("document_id").equal(
                    obj.properties["document_id"]
                ),
                total_count=True
            ).total_count
            
            documents.append({
                "document_id": obj.properties["document_id"],
                "filename": obj.properties["filename"],
                "timestamp": obj.properties["timestamp"],
                "chunk_count": chunk_count
            })
    
    return documents

def get_document_metadata(collection: Any, document_id: str) -> Optional[Dict]:
    """Get full metadata for a specific document"""
    result = collection.query.fetch_objects(
        limit=1,
        filters=Filter.by_property("document_id").equal(document_id),
        return_properties=[
            "document_id", 
            "filename", 
            "timestamp", 
            "source_url",
            "mime_type",
            "fingerprint",
            "summary"
        ],
        include_vector=False
    )
    
    if not result.objects:
        return None
    
    first_chunk = result.objects[0]
    return {
        "document_id": document_id,
        "filename": first_chunk.properties["filename"],
        "timestamp": first_chunk.properties["timestamp"],
        "source_url": first_chunk.properties.get("source_url", ""),
        "mime_type": first_chunk.properties["mime_type"],
        "fingerprint": first_chunk.properties["fingerprint"],
        "summary": first_chunk.properties.get("summary", ""),
        "total_chunks":  collection.aggregate.over_all(
            filters=Filter.by_property("document_id").equal(document_id),
            total_count=True
        ).total_count
    }

def search_collection(
    collection: Any,
    query: str,
    embed_model: TextEmbedding,
    limit: int = 10,
    filters: Optional[Dict] = None
) -> List[Dict]:
    """Search documents with filter support"""
    query_vector = list(embed_model.embed([query]))[0].tolist()
    
    search_params = {
        "limit": limit,
        "return_metadata": ["distance"],
        "return_properties": ["filename", "content", "source_url", "timestamp"]
    }
    
    if filters and len(filters) == 1:
        key, value = next(iter(filters.items()))
        search_params["filters"] = Filter.by_property(key).equal(value)
    
    # Execute search
    result = collection.query.near_vector(
        near_vector=query_vector,
        **search_params
    )
    
    return [
        {
            "filename": obj.properties.get("filename", "Unknown"),
            "content": obj.properties.get("content", ""),
            "source_url": obj.properties.get("source_url", ""),
            "timestamp": obj.properties.get("timestamp", ""),
            "distance": obj.metadata.distance
        }
        for obj in result.objects
    ] 
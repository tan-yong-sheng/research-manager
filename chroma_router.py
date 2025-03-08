
# ChromaDB API endpoints
@app.get("/api/chroma/collections")
async def list_collections():
    """List all ChromaDB collections"""
    try:
        collections = chroma_client.list_collections()
        return {"collections": [{"name": col.name, "metadata": col.metadata} for col in collections]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list collections: {str(e)}")

@app.post("/api/chroma/collections")
async def create_collection(collection_data: CollectionCreate):
    """Create a new ChromaDB collection"""
    try:
        new_collection = chroma_client.create_collection(
            name=collection_data.name,
            metadata=collection_data.metadata
        )
        return {
            "name": new_collection.name,
            "metadata": new_collection.metadata,
            "message": f"Collection '{collection_data.name}' created successfully"
        }
    except Exception as e:
        if "already exists" in str(e).lower():
            raise HTTPException(status_code=409, detail=f"Collection '{collection_data.name}' already exists")
        raise HTTPException(status_code=500, detail=f"Failed to create collection: {str(e)}")

@app.get("/api/chroma/collections/{collection_name}")
async def get_collection(collection_name: str):
    """Get information about a specific ChromaDB collection"""
    try:
        collection = chroma_client.get_collection(name=collection_name)
        count = collection.count()
        return {
            "name": collection.name,
            "metadata": collection.metadata,
            "count": count
        }
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Collection '{collection_name}' not found")

@app.put("/api/chroma/collections/{collection_name}")
async def update_collection_metadata(collection_name: str, data: CollectionUpdate):
    """Update a collection's metadata"""
    try:
        collection = chroma_client.get_collection(name=collection_name)
        collection.modify(metadata=data.metadata)
        return {
            "name": collection.name,
            "metadata": collection.metadata,
            "message": f"Collection '{collection_name}' metadata updated successfully"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update collection: {str(e)}")

@app.delete("/api/chroma/collections/{collection_name}")
async def delete_collection(collection_name: str):
    """Delete a ChromaDB collection"""
    try:
        chroma_client.delete_collection(name=collection_name)
        return {"message": f"Collection '{collection_name}' deleted successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete collection: {str(e)}")

@app.get("/api/chroma/collections/{collection_name}/documents")
async def list_documents(
    collection_name: str, 
    limit: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0)
):
    """List documents in a collection with pagination"""
    try:
        collection = chroma_client.get_collection(name=collection_name)
        total_count = collection.count()
        
        # Handle empty collection
        if total_count == 0:
            return {
                "total": 0,
                "documents": [],
                "offset": offset,
                "limit": limit
            }
        
        # Get document IDs first
        all_ids = collection.get(include=[])["ids"]
        paginated_ids = all_ids[offset:offset+limit]
        
        # Get the specific documents
        results = collection.get(
            ids=paginated_ids,
            include=["documents", "metadatas", "embeddings"]
        )
        
        documents = []
        for i in range(len(results["ids"])):
            doc = {
                "id": results["ids"][i],
                "metadata": results["metadatas"][i] if "metadatas" in results else None,
                "document": results["documents"][i] if "documents" in results else None,
                "has_embedding": "embeddings" in results
            }
            documents.append(doc)
            
        return {
            "total": total_count,
            "documents": documents,
            "offset": offset,
            "limit": limit
        }
    except Exception as e:
        if "not found" in str(e).lower():
            raise HTTPException(status_code=404, detail=f"Collection '{collection_name}' not found")
        raise HTTPException(status_code=500, detail=f"Failed to list documents: {str(e)}")

@app.get("/api/chroma/collections/{collection_name}/documents/{document_id}")
async def get_document(collection_name: str, document_id: str):
    """Get a specific document from a collection"""
    try:
        collection = chroma_client.get_collection(name=collection_name)
        result = collection.get(
            ids=[document_id],
            include=["documents", "metadatas", "embeddings"]
        )
        
        if not result["ids"]:
            raise HTTPException(status_code=404, detail=f"Document with ID '{document_id}' not found")
            
        document_data = {
            "id": result["ids"][0],
            "metadata": result["metadatas"][0] if "metadatas" in result and result["metadatas"] else None,
            "document": result["documents"][0] if "documents" in result and result["documents"] else None,
            "has_embedding": "embeddings" in result and len(result["embeddings"]) > 0
        }
        
        return document_data
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get document: {str(e)}")

@app.post("/api/chroma/collections/{collection_name}/documents")
async def add_documents(collection_name: str, data: DocumentsAdd):
    """Add documents to a collection"""
    if len(data.documents) != len(data.ids):
        raise HTTPException(
            status_code=400, 
            detail="Number of documents and IDs must be equal"
        )
        
    if data.metadatas and len(data.metadatas) != len(data.documents):
        raise HTTPException(
            status_code=400, 
            detail="Number of metadatas must equal number of documents"
        )
        
    try:
        collection = chroma_client.get_collection(name=collection_name)
        
        # Generate embeddings automatically via ChromaDB's embedding function
        collection.add(
            documents=data.documents,
            metadatas=data.metadatas,
            ids=data.ids
        )
        
        return {
            "message": f"Added {len(data.documents)} documents to collection '{collection_name}'",
            "ids": data.ids
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to add documents: {str(e)}")

@app.put("/api/chroma/collections/{collection_name}/documents")
async def update_documents(collection_name: str, data: DocumentsUpdate):
    """Update documents in a collection"""
    if not data.documents and not data.metadatas:
        raise HTTPException(
            status_code=400,
            detail="At least one of documents or metadatas must be provided"
        )
        
    if data.documents and len(data.documents) != len(data.ids):
        raise HTTPException(
            status_code=400,
            detail="Number of documents must equal number of IDs"
        )
        
    if data.metadatas and len(data.metadatas) != len(data.ids):
        raise HTTPException(
            status_code=400,
            detail="Number of metadatas must equal number of IDs"
        )
        
    try:
        collection = chroma_client.get_collection(name=collection_name)
        
        # Update using ChromaDB's update method
        collection.update(
            ids=data.ids,
            documents=data.documents,
            metadatas=data.metadatas
        )
        
        return {
            "message": f"Updated {len(data.ids)} documents in collection '{collection_name}'",
            "ids": data.ids
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update documents: {str(e)}")

@app.delete("/api/chroma/collections/{collection_name}/documents")
async def delete_documents(collection_name: str, ids: List[str]):
    """Delete documents from a collection"""
    if not ids:
        raise HTTPException(status_code=400, detail="At least one document ID is required")
        
    try:
        collection = chroma_client.get_collection(name=collection_name)
        collection.delete(ids=ids)
        
        return {
            "message": f"Deleted {len(ids)} documents from collection '{collection_name}'",
            "ids": ids
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete documents: {str(e)}")

@app.post("/api/chroma/collections/{collection_name}/query")
async def query_collection(collection_name: str, query: QueryRequest):
    """Query a collection for similar documents"""
    if not query.query_texts and not query.query_embeddings:
        raise HTTPException(
            status_code=400,
            detail="Either query_texts or query_embeddings must be provided"
        )
        
    try:
        collection = chroma_client.get_collection(name=collection_name)
        
        results = collection.query(
            query_texts=query.query_texts,
            query_embeddings=query.query_embeddings,
            n_results=query.n_results,
            where=query.where,
            where_document=query.where_document,
            include=["documents", "metadatas", "distances"]
        )
        
        return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to query collection: {str(e)}")

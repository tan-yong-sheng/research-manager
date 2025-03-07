import os
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, File, UploadFile, HTTPException, Form, Body, Query
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import chromadb
from pypdf import PdfReader
import shutil
from datetime import datetime
from pydantic import BaseModel
from openai import OpenAI
from dotenv import load_dotenv
import json
import re
import uuid

# Load environment variables
load_dotenv()

# Initialize OpenAI client
client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    base_url=os.getenv("OPENAI_BASE_URL")
)

# Initialize FastAPI app
app = FastAPI(title="Research Papers Assistant")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # For development only - configure properly in production
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],  # Explicitly list allowed methods
    allow_headers=["*"],
)

# Initialize ChromaDB with new configuration
chroma_client = chromadb.PersistentClient(path="db")

# Create collection for research papers
collection = chroma_client.get_or_create_collection(name="research_papers")

# Ensure research_papers directory exists
UPLOAD_DIR = "research_papers"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Define models
class PaperMetadata(BaseModel):
    title: str
    authors: str = ""
    year: Optional[int] = None
    keywords: List[str] = []
    tags: List[str] = []
    category: Optional[str] = None
    abstract: Optional[str] = ""
    folder_id: Optional[str] = None  # Reference to folder

class Folder(BaseModel):
    id: str
    name: str
    parent_id: Optional[str] = None
    description: Optional[str] = ""
    
class FolderCreate(BaseModel):
    name: str
    parent_id: Optional[str] = None
    description: Optional[str] = ""
    
class FolderUpdate(BaseModel):
    name: Optional[str] = None
    parent_id: Optional[str] = None
    description: Optional[str] = None

# Initialize folder storage
FOLDER_FILE = "folders.json"

def load_folders():
    """Load folders from JSON file and ensure Default Library exists"""
    if os.path.exists(FOLDER_FILE):
        with open(FOLDER_FILE, "r") as f:
            folders_data = json.load(f)
    else:
        folders_data = {"folders": []}

    # Ensure Default Library exists
    if not any(f["id"] == "default" for f in folders_data["folders"]):
        ## add default folder
        folders_data["folders"].append({
            "id": "default",
            "name": "Default",
            "parent_id": None,
            "description": "Default folder for papers"
        })
        ## add trash folder
        folders_data["folders"].append({
            "id": "trash",
            "name": "Trash",
            "parent_id": None,
            "description": "Trash folder for papers"
        })
        save_folders(folders_data)

    return folders_data

def save_folders(folders_data):
    with open(FOLDER_FILE, "w") as f:
        json.dump(folders_data, f)

# Helper functions
def clean_text(text: str) -> str:
    """Clean text to remove problematic characters."""
    # Replace problematic Unicode surrogates and control characters
    text = re.sub(r'[\ud800-\udfff]', '', text)
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
    return text

def extract_text_from_pdf(file_path: str) -> str:
    """Extract text content from a PDF file."""
    reader = PdfReader(file_path)
    text = ""
    for page in reader.pages:
        try:
            page_text = page.extract_text() or ""
            text += clean_text(page_text) + "\n"
        except Exception as e:
            # If extraction fails for a page, continue with whatever we have
            print(f"Warning: Could not extract text from page: {str(e)}")
            continue
    return text

def get_embedding(text: str) -> List[float]:
    """Generate embeddings using OpenAI's API."""
    response = client.embeddings.create(
        model="text-embedding-ada-002",
        input=text
    )
    return response.data[0].embedding

def sanitize_filename(title: str, original_extension: str = ".pdf") -> str:
    """Convert a title to a valid filename."""
    # Remove invalid characters and replace spaces with underscores
    filename = re.sub(r'[<>:"/\\|?*]', '', title)
    filename = filename.replace(' ', '_')
    
    # Ensure the filename ends with .pdf
    if not filename.lower().endswith(original_extension):
        filename += original_extension
        
    return filename

def ensure_unique_filename(base_filename: str, directory: str) -> str:
    """Ensure filename is unique by adding a number if necessary."""
    filename = base_filename
    counter = 1
    
    # Split filename into name and extension
    name, ext = os.path.splitext(filename)
    
    while os.path.exists(os.path.join(directory, filename)):
        filename = f"{name}_{counter}{ext}"
        counter += 1
        
    return filename

# Serve the main index.html page
@app.get("/", response_class=HTMLResponse)
async def read_root():
    """Serve the main HTML page"""
    with open("index.html", "r") as f:
        html_content = f.read()
    return HTMLResponse(content=html_content)

# Serve static files (JavaScript, CSS)
app.mount("/static", StaticFiles(directory="."), name="static")

@app.get("/stats")
async def get_stats():
    """Get statistics about the paper collection"""
    try:
        results = collection.get(include=["metadatas"])
        papers = results["metadatas"] if results["metadatas"] else []
    except Exception as e:
        # Return empty stats if there's an error or empty collection
        return {
            "total_papers": 0,
            "categories": {},
            "tags": [],
            "years": {}
        }
    
    # Collect stats
    total_papers = len(papers)
    categories = {}
    tags = set()
    years = {}
    
    for paper in papers:
        # Count categories
        category = paper.get("category")
        if category:
            categories[category] = categories.get(category, 0) + 1
            
        # Collect unique tags - handle JSON string format
        paper_tags = paper.get("tags", "[]")
        if isinstance(paper_tags, str):
            try:
                # Parse JSON string to list
                parsed_tags = json.loads(paper_tags)
                if isinstance(parsed_tags, list):
                    tags.update(parsed_tags)
            except json.JSONDecodeError:
                print(f"Warning: Could not parse tags JSON: {paper_tags}")
        elif isinstance(paper_tags, list):
            tags.update(paper_tags)
        
        # Count papers by year
        year = paper.get("year")
        if year:
            years[year] = years.get(year, 0) + 1
    
    return {
        "total_papers": total_papers,
        "categories": categories,
        "tags": list(tags),
        "years": years
    }

@app.get("/papers/by-tag/{tag}")
async def get_papers_by_tag(tag: str):
    """Get papers with specific tag"""
    try:
        results = collection.get(include=["metadatas"])
        papers = []
        for paper in results["metadatas"]:
            # Skip papers that are in the trash folder
            if paper.get("folder_id") == "trash":
                continue
                
            paper_tags = paper.get("tags", "[]")
            # Parse tags if they're stored as JSON string
            if isinstance(paper_tags, str):
                try:
                    parsed_tags = json.loads(paper_tags)
                    if isinstance(parsed_tags, list) and tag in parsed_tags:
                        papers.append(paper)
                except json.JSONDecodeError:
                    print(f"Warning: Could not parse tags JSON: {paper_tags}")
            elif isinstance(paper_tags, list) and tag in paper_tags:
                papers.append(paper)
    except Exception as e:
        print(f"Error in get_papers_by_tag: {str(e)}")
        papers = []
    return {"papers": papers}

@app.get("/papers/by-category/{category}")
async def get_papers_by_category(category: str):
    """Get papers in specific category"""
    try:
        results = collection.get(include=["metadatas"])
        papers = [
            paper for paper in results["metadatas"]
            if paper.get("category") == category and paper.get("folder_id") != "trash"
        ]
    except Exception:
        papers = []
    return {"papers": papers}

async def check_file_exists(filename: str) -> bool:
    """Check if a file with the given filename exists in any folder."""
    try:
        results = collection.get(ids=[filename], include=["metadatas"])
        return bool(results["ids"])
    except Exception:
        return False

@app.post("/papers/")
async def upload_paper(
    file: UploadFile = File(...),
    metadata: Optional[str] = Form(None),
    folder_id: Optional[str] = Form('default'),  # Default to 'default' folder
    override: bool = Form(False)  # New parameter to handle overrides
):
    """Upload a research paper and store its embedding."""
    if not file.filename.endswith('.pdf'):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")
    
    # Validate folder if specified
    if folder_id:
        folders_data = load_folders()
        folder_exists = any(f["id"] == folder_id for f in folders_data["folders"])
        if not folder_exists:
            raise HTTPException(status_code=404, detail="Folder not found")
    
    # Parse metadata
    try:
        metadata_dict = json.loads(metadata) if metadata else {}
        if not metadata_dict.get('title'):
            metadata_dict['title'] = os.path.splitext(file.filename)[0]  # Use original filename without extension as title
    except json.JSONDecodeError:
        metadata_dict = {'title': os.path.splitext(file.filename)[0]}
    
    # Create a sanitized filename from the title
    original_ext = os.path.splitext(file.filename)[1].lower()
    sanitized_filename = sanitize_filename(metadata_dict['title'], original_ext)
    
    # Check if file exists
    if await check_file_exists(sanitized_filename):
        if not override:
            raise HTTPException(
                status_code=409,  # Conflict
                detail={
                    "message": "File with this name already exists",
                    "filename": sanitized_filename,
                    "requires_override": True
                }
            )
        # If override is True, we'll continue and replace the existing file
    else:
        # If file doesn't exist, ensure unique filename
        sanitized_filename = ensure_unique_filename(sanitized_filename, UPLOAD_DIR)
    
    # Save the file with the new filename
    file_path = os.path.join(UPLOAD_DIR, sanitized_filename)
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    # Extract text and generate embedding
    try:
        text = extract_text_from_pdf(file_path)
        
        # Ensure the text is not empty
        if not text.strip():
            # Clean up file if text extraction fails
            os.remove(file_path)
            raise ValueError("No text could be extracted from the PDF file.")
        
        # Truncate text if it's too long (OpenAI has token limits)
        # Roughly 8000 chars is about 2000 tokens which is a safe limit
        if len(text) > 8000:
            text = text[:8000]
            
        embedding = get_embedding(text)
        
        # Prepare sanitized metadata for ChromaDB
        sanitized_metadata = {
            "filename": sanitized_filename,  # Store the new filename
            "upload_date": str(datetime.now()),
            "title": metadata_dict.get('title', sanitized_filename),
            "authors": metadata_dict.get('authors', "")
        }
        
        # Add folder_id to metadata, defaulting to 'default'
        sanitized_metadata["folder_id"] = folder_id
        
        # Handle keywords (convert list to JSON string if needed)
        keywords = metadata_dict.get('keywords', [])
        if isinstance(keywords, list):
            sanitized_metadata["keywords"] = json.dumps(keywords)
        else:
            sanitized_metadata["keywords"] = "[]"
            
        # Handle tags (convert list to JSON string if needed)
        tags = metadata_dict.get('tags', [])
        if isinstance(tags, list):
            sanitized_metadata["tags"] = json.dumps(tags)
        else:
            sanitized_metadata["tags"] = "[]"
        
        # Handle abstract
        sanitized_metadata["abstract"] = metadata_dict.get('abstract', "")
        
        # Handle year field (must be int or str, not None)
        year = metadata_dict.get('year')
        if year is not None:
            sanitized_metadata["year"] = year
        
        # Handle category field (must be str, not None)
        category = metadata_dict.get('category')
        if category is not None and category != "":
            sanitized_metadata["category"] = category

        # Delete existing document if overriding
        if override:
            try:
                collection.delete(ids=[sanitized_filename])
            except Exception:
                pass
        
        # Store in ChromaDB
        collection.add(
            documents=[text],
            embeddings=[embedding],
            metadatas=[sanitized_metadata],
            ids=[sanitized_filename]  # Use the new filename as ID
        )
        return {"message": "Paper uploaded successfully", "filename": sanitized_filename}
    except Exception as e:
        # Clean up file if processing fails
        if os.path.exists(file_path):
            os.remove(file_path)
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/papers/{filename}/metadata")
async def update_paper_metadata(filename: str, metadata: Dict[str, Any]):
    """Update paper metadata"""
    try:
        # Get existing metadata
        results = collection.get(
            ids=[filename],
            include=["metadatas", "documents", "embeddings"]
        )
        
        if not results["ids"]:
            raise HTTPException(status_code=404, detail="Paper not found")
        
        # Update metadata while preserving existing data
        existing_metadata = results["metadatas"][0]
        
        # Convert None values to appropriate types for ChromaDB
        updated_metadata = {
            "filename": filename,
            "upload_date": existing_metadata["upload_date"],
            "title": metadata.get("title") or existing_metadata.get("title", ""),
            "authors": metadata.get("authors") or existing_metadata.get("authors", ""),
            "year": metadata.get("year") if metadata.get("year") is not None else existing_metadata.get("year", ""),
            "category": metadata.get("category") or existing_metadata.get("category", ""),
            "tags": json.dumps(metadata.get("tags", [])),  # Convert tags list to JSON string
            "abstract": metadata.get("abstract") or existing_metadata.get("abstract", ""),
            "folder_id": metadata.get("folder_id") or existing_metadata.get("folder_id", "default")
        }
        
        # Update in ChromaDB
        collection.update(
            ids=[filename],
            metadatas=[updated_metadata]
        )
        
        return {"message": "Metadata updated successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/papers/")
async def list_papers():
    """List all stored papers."""
    try:
        results = collection.get(include=["metadatas"])
        return {"papers": results["metadatas"] if results["metadatas"] else []}
    except Exception:
        return {"papers": []}

@app.get("/papers/{filename}")
async def get_paper(filename: str):
    """Download a specific paper."""
    file_path = os.path.join(UPLOAD_DIR, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Paper not found")
    return FileResponse(file_path)

@app.get("/papers/{filename}/metadata")
async def get_paper_metadata(filename: str):
    """Get metadata for a specific paper."""
    try:
        results = collection.get(
            ids=[filename],
            include=["metadatas"]
        )
        
        if not results["ids"]:
            raise HTTPException(status_code=404, detail="Paper not found")
            
        return results["metadatas"][0]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/papers/{filename}")
async def delete_paper(filename: str, soft_delete: bool = True):
    """Delete a paper. If soft_delete=True, moves it to trash folder, otherwise permanently deletes it."""
    try:
        # Get existing metadata first
        results = collection.get(
            ids=[filename],
            include=["metadatas"]
        )
        
        if not results["ids"]:
            raise HTTPException(status_code=404, detail="Paper not found")
        
        current_metadata = results["metadatas"][0]
        file_path = os.path.join(UPLOAD_DIR, filename)
        
        if soft_delete and current_metadata.get("folder_id") != "trash":
            # Store original folder_id and move to trash
            current_metadata["original_folder_id"] = current_metadata.get("folder_id")
            current_metadata["folder_id"] = "trash"
            collection.update(
                ids=[filename],
                metadatas=[current_metadata]
            )
            return {"message": "Paper moved to trash"}
        else:
            # Hard delete - remove from database and file system
            collection.delete(ids=[filename])
            if os.path.exists(file_path):
                os.remove(file_path)
            return {"message": "Paper permanently deleted"}
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/search/")
async def search_papers(query: str, n_results: int = 5):
    """Search papers by similarity."""
    if not query:
        raise HTTPException(status_code=400, detail="Query cannot be empty")
        
    try:
        query_embedding = get_embedding(query)
        
        # Handle empty collection gracefully
        try:
            results = collection.query(
                query_embeddings=[query_embedding],
                n_results=n_results,
                include=["metadatas", "documents"]
            )
            
            return {
                "results": [
                    {
                        "metadata": meta,
                        "content": doc[:1000] + "..." if len(doc) > 1000 else doc
                    }
                    for meta, doc in zip(results["metadatas"][0], results["documents"][0])
                ]
            }
        except Exception as query_error:
            # If collection is empty or other error
            return {"results": []}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Folder Management Endpoints
@app.get("/folders/")
async def list_folders():
    """List all folders"""
    folders_data = load_folders()
    return folders_data

@app.post("/folders/", response_model=Folder)
async def create_folder(folder: FolderCreate):
    """Create a new folder"""
    folders_data = load_folders()
    
    # Check if folder with same name already exists at the same level
    existing_folders = folders_data["folders"]
    for existing_folder in existing_folders:
        if existing_folder["name"].lower() == folder.name.lower() and existing_folder["parent_id"] == folder.parent_id:
            raise HTTPException(
                status_code=409,
                detail="A folder with this name already exists at this level"
            )
    
    # Create new folder with UUID
    new_folder = {
        "id": str(uuid.uuid4()),
        "name": folder.name,
        "parent_id": folder.parent_id,
        "description": folder.description
    }
    
    folders_data["folders"].append(new_folder)
    save_folders(folders_data)
    
    return new_folder

@app.put("/folders/{folder_id}", response_model=Folder)
async def update_folder(folder_id: str, folder_update: FolderUpdate):
    """Update a folder"""
    if folder_id == "default":
        raise HTTPException(status_code=400, detail="Cannot modify Default Library")
        
    folders_data = load_folders()
    
    # Find the folder to update
    folder_index = None
    for i, folder in enumerate(folders_data["folders"]):
        if folder["id"] == folder_id:
            folder_index = i
            break
    
    if folder_index is None:
        raise HTTPException(status_code=404, detail="Folder not found")
    
    # Get folder's current state
    current_folder = folders_data["folders"][folder_index]
    
    # Check for duplicate name only if name is being updated
    if folder_update.name is not None and folder_update.name != current_folder["name"]:
        parent_id = folder_update.parent_id if folder_update.parent_id is not None else current_folder["parent_id"]
        for existing_folder in folders_data["folders"]:
            if (existing_folder["name"].lower() == folder_update.name.lower() and 
                existing_folder["parent_id"] == parent_id and 
                existing_folder["id"] != folder_id):
                raise HTTPException(
                    status_code=409,
                    detail="A folder with this name already exists at this level"
                )
    
    # Update folder fields
    if folder_update.name is not None:
        current_folder["name"] = folder_update.name
    
    if folder_update.description is not None:
        current_folder["description"] = folder_update.description
    
    if folder_update.parent_id is not None:
        # Validate parent folder if specified
        if folder_update.parent_id:
            parent_exists = any(f["id"] == folder_update.parent_id for f in folders_data["folders"])
            if not parent_exists:
                raise HTTPException(status_code=404, detail="Parent folder not found")
            
            # Check for circular reference
            if folder_update.parent_id == folder_id:
                raise HTTPException(status_code=400, detail="Folder cannot be its own parent")
        
        current_folder["parent_id"] = folder_update.parent_id
    
    folders_data["folders"][folder_index] = current_folder
    save_folders(folders_data)
    
    return current_folder

@app.delete("/folders/{folder_id}")
async def delete_folder(
    folder_id: str, 
    trash_folder_id: Optional[str] = Query(None),
    move_papers: bool = True
):
    """Delete a folder and move its papers to the trash folder"""
    if folder_id == "default":
        raise HTTPException(status_code=400, detail="Cannot delete Default Library")
    
    if folder_id == "trash":
        raise HTTPException(status_code=400, detail="Cannot delete the Trash folder")
        
    folders_data = load_folders()
    
    # Check if folder exists and get it
    folder_exists = False
    for i, folder in enumerate(folders_data["folders"]):
        if folder["id"] == folder_id:
            folder_exists = True
            folders_data["folders"].pop(i)
            break
    
    if not folder_exists:
        raise HTTPException(status_code=404, detail="Folder not found")

    # Always use trash folder by default, override if specific trash_folder_id provided
    destination_folder_id = "trash"
    if trash_folder_id and trash_folder_id != "trash":
        if any(f["id"] == trash_folder_id for f in folders_data["folders"]):
            destination_folder_id = trash_folder_id
        else:
            raise HTTPException(status_code=404, detail="Specified destination folder not found")
    
    # Move papers to trash folder
    if move_papers:
        try:
            # Get all papers first
            results = collection.get(include=["metadatas", "documents", "embeddings"])
            if results and results["ids"]:
                for i, metadata in enumerate(results["metadatas"]):
                    if metadata.get("folder_id") == folder_id:
                        # Create updated metadata with new folder_id
                        updated_metadata = dict(metadata)
                        updated_metadata["folder_id"] = destination_folder_id
                        
                        # Update the paper in ChromaDB
                        collection.update(
                            ids=[results["ids"][i]],
                            metadatas=[updated_metadata],
                            documents=[results["documents"][i]],
                            embeddings=[results["embeddings"][i]]
                        )
        except Exception as e:
            print(f"Error moving papers: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Failed to move papers: {str(e)}")
    
    # Update child folders to be under trash folder too
    for folder in folders_data["folders"]:
        if folder.get("parent_id") == folder_id:
            folder["parent_id"] = destination_folder_id
    
    save_folders(folders_data)
    
    return {"message": "Folder deleted successfully"}

@app.get("/papers/by-folder/{folder_id}")
async def get_papers_by_folder(folder_id: str):
    """Get papers in a specific folder"""
    try:
        results = collection.get(include=["metadatas"])
        papers = []
        
        for paper in results["metadatas"]:
            # Check if paper is in this folder
            paper_folder_id = paper.get("folder_id")
            if paper_folder_id == folder_id:
                papers.append(paper)
    except Exception:
        papers = []
        
    return {"papers": papers}

@app.put("/papers/{filename}/move")
async def move_paper(filename: str, folder_id: Optional[str] = None):
    """Move a paper to a different folder"""
    # Validate folder if specified
    if folder_id:
        folders_data = load_folders()
        folder_exists = any(f["id"] == folder_id for f in folders_data["folders"])
        if not folder_exists:
            raise HTTPException(status_code=404, detail="Folder not found")
    
    try:
        # Get existing metadata
        results = collection.get(
            ids=[filename],
            include=["metadatas"]
        )
        
        if not results["ids"]:
            raise HTTPException(status_code=404, detail="Paper not found")
        
        # Update metadata with new folder
        metadata = results["metadatas"][0]
        
        # If moving to trash, store original folder
        if folder_id == "trash" and metadata.get("folder_id") != "trash":
            metadata["original_folder_id"] = metadata.get("folder_id")
        # If moving out of trash, remove original folder reference
        elif metadata.get("folder_id") == "trash":
            metadata.pop("original_folder_id", None)
            
        metadata["folder_id"] = folder_id
        
        collection.update(
            ids=[filename],
            metadatas=[metadata]
        )
        
        return {"message": "Paper moved successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
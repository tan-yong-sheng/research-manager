import os
import sqlite3
import threading
import time
from typing import Optional, Dict
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from pdfminer.high_level import extract_text
from openai import OpenAI
import chromadb
import json
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Initialize DB for queue
def init_queue_db():
    conn = sqlite3.connect('paper_queue.db', check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS processing_queue (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        file_path TEXT UNIQUE,
        status TEXT DEFAULT 'pending',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        metadata TEXT
    )
    ''')
    conn.commit()
    return conn

# File event handler for new PDFs
class PaperHandler(FileSystemEventHandler):
    def __init__(self, db_conn):
        self.db_conn = db_conn
        # Lock to ensure thread-safety when using SQLite
        self.db_lock = threading.RLock()
    
    def on_created(self, event):
        if event.src_path.endswith('.pdf'):
            # Add to queue
            with self.db_lock:
                cursor = self.db_conn.cursor()
                try:
                    cursor.execute(
                        "INSERT INTO processing_queue (file_path) VALUES (?)",
                        (event.src_path,)
                    )
                    self.db_conn.commit()
                    print(f"Queued: {event.src_path}")
                except sqlite3.IntegrityError:
                    print(f"Already in queue: {event.src_path}")

# Processing worker to handle the embedding generation queue
def process_queue(db_conn, client, chroma_client, db_lock, collection_name="research_papers", embedding_model="text-embedding-3-small"):
    collection = chroma_client.get_or_create_collection(collection_name)
    
    while True:
        # Get next item from queue
        with db_lock:
            cursor = db_conn.cursor()
            cursor.execute(
                "SELECT id, file_path, metadata FROM processing_queue WHERE status = 'pending' LIMIT 1"
            )
            result = cursor.fetchone()
            
            if result:
                item_id, file_path, metadata_json = result
                # Mark as processing
                cursor.execute(
                    "UPDATE processing_queue SET status = 'processing' WHERE id = ?",
                    (item_id,)
                )
                db_conn.commit()
        
        if result:
            try:
                print(f"Processing: {file_path}")
                # Extract text
                text = extract_text(file_path)
                
                # Parse metadata if available
                metadata = {}
                if metadata_json:
                    try:
                        metadata = json.loads(metadata_json)
                    except json.JSONDecodeError:
                        print(f"Warning: Invalid metadata JSON: {metadata_json}")
                
                # Simple chunking (configurable chunk size)
                chunk_size = int(os.getenv("CHUNK_SIZE", "4000"))
                chunk_overlap = int(os.getenv("CHUNK_OVERLAP", "1000"))
                step_size = chunk_size - chunk_overlap
                
                chunks = []
                for i in range(0, len(text), step_size):
                    if i + chunk_size <= len(text):
                        chunks.append(text[i:i + chunk_size])
                    else:
                        chunks.append(text[i:])
                        break
                
                if not chunks:
                    chunks = [""]  # Handle empty files
                
                # Get embeddings
                embeddings = []
                for chunk in chunks:
                    response = client.embeddings.create(
                        input=chunk,
                        model=embedding_model
                    )
                    embeddings.append(response.data[0].embedding)
                    # Rate limiting to avoid API limits
                    time.sleep(0.5)
                
                # Basic metadata if not provided
                filename = os.path.basename(file_path)
                if not metadata:
                    metadata = {"source": file_path, "filename": filename}
                
                # Store in ChromaDB
                collection.add(
                    embeddings=embeddings,
                    documents=chunks,
                    metadatas=[metadata] * len(chunks),
                    ids=[f"{filename}_{i}" for i in range(len(chunks))]
                )
                
                # Mark as completed
                with db_lock:
                    cursor = db_conn.cursor()
                    cursor.execute(
                        "UPDATE processing_queue SET status = 'completed' WHERE id = ?",
                        (item_id,)
                    )
                    db_conn.commit()
                print(f"Processed: {file_path}")
                
            except Exception as e:
                # Mark as failed
                with db_lock:
                    cursor = db_conn.cursor()
                    cursor.execute(
                        "UPDATE processing_queue SET status = 'failed' WHERE id = ?",
                        (item_id,)
                    )
                    db_conn.commit()
                print(f"Error processing {file_path}: {str(e)}")
        
        # Sleep to avoid high CPU usage
        time.sleep(1)

# Service class to manage the embedding pipeline
class EmbeddingService:
    _instance = None
    _initialized = False
    _observer = None
    _processing_thread = None
    _db_conn = None
    _db_lock = None
    _openai_client = None
    _chroma_client = None
    
    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def __init__(self):
        # Singleton pattern - ensure only one instance exists
        if EmbeddingService._initialized:
            return
        
        self.monitor_dir = "research_papers"
        self._db_conn = init_queue_db()
        self._db_lock = threading.RLock()
        self._openai_client = OpenAI(
            api_key=os.getenv("OPENAI_API_KEY"),
            base_url=os.getenv("OPENAI_BASE_URL")
        )
        self._chroma_client = chromadb.PersistentClient(path="./db")
        EmbeddingService._initialized = True
    
    # Start the embedding pipeline
    def start(self):
        if self._observer and self._observer.is_alive():
            return  # Already running
            
        # Start file watcher
        event_handler = PaperHandler(self._db_conn)
        self._observer = Observer()
        self._observer.schedule(event_handler, self.monitor_dir, recursive=True)
        self._observer.start()
        
        # Start processing thread
        self._processing_thread = threading.Thread(
            target=process_queue,
            args=(
                self._db_conn, 
                self._openai_client, 
                self._chroma_client,
                self._db_lock,  # Pass the lock to the worker
                os.getenv("CHROMA_COLLECTION_NAME", "research_papers"),
                os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
            ),
            daemon=True
        )
        self._processing_thread.start()
        
        # Process existing files in directory (optional)
        with self._db_lock:
            for root, _, files in os.walk(self.monitor_dir):
                for file in files:
                    if file.endswith('.pdf'):
                        path = os.path.join(root, file)
                        cursor = self._db_conn.cursor()
                        try:
                            cursor.execute(
                                "INSERT INTO processing_queue (file_path) VALUES (?)",
                                (path,)
                            )
                            self._db_conn.commit()
                        except sqlite3.IntegrityError:
                            pass  # Already in queue
        
        print(f"Embedding service started - monitoring {self.monitor_dir}")
    
    # Stop the embedding pipeline
    def stop(self):
        if self._observer:
            self._observer.stop()
            self._observer.join()
            self._observer = None
            print("Embedding service stopped")
    
    # Queue a file for processing with optional metadata
    def queue_file(self, file_path: str, metadata: Optional[Dict] = None):
        with self._db_lock:
            cursor = self._db_conn.cursor()
            metadata_json = json.dumps(metadata) if metadata else None
            
            try:
                cursor.execute(
                    "INSERT INTO processing_queue (file_path, metadata) VALUES (?, ?)",
                    (file_path, metadata_json)
                )
                self._db_conn.commit()
                print(f"Manually queued: {file_path}")
                return True
            except sqlite3.IntegrityError:
                print(f"File already in queue: {file_path}")
                # If already exists, update the metadata
                if metadata:
                    cursor.execute(
                        "UPDATE processing_queue SET metadata = ? WHERE file_path = ? AND status = 'pending'",
                        (metadata_json, file_path)
                    )
                    self._db_conn.commit()
                return False
    
    # Get queue status
    def get_queue_status(self):
        with self._db_lock:
            cursor = self._db_conn.cursor()
            cursor.execute(
                "SELECT status, COUNT(*) FROM processing_queue GROUP BY status"
            )
            results = cursor.fetchall()
            
            status_counts = {
                "pending": 0,
                "processing": 0,
                "completed": 0,
                "failed": 0
            }
            
            for status, count in results:
                status_counts[status] = count
                
            return status_counts

# Initialize the service in standalone mode
if __name__ == "__main__":
    service = EmbeddingService.get_instance()
    service.start()
    
    try:
        print("Embedding pipeline started. Press Ctrl+C to stop.")
        print(f"Monitoring '{service.monitor_dir}' folder for new PDF files...")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        service.stop()
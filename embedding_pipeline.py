import os
import sqlite3
import threading
import time
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
    conn = sqlite3.connect('paper_queue.db')
    cursor = conn.cursor()
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS processing_queue (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        file_path TEXT UNIQUE,
        status TEXT DEFAULT 'pending',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    conn.commit()
    return conn

# File event handler
class PaperHandler(FileSystemEventHandler):
    def __init__(self, db_conn):
        self.db_conn = db_conn
    
    def on_created(self, event):
        if event.src_path.endswith('.pdf'):
            # Add to queue
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

# Processing worker
def process_queue(db_conn, client, chroma_client):
    collection = chroma_client.get_or_create_collection("research_papers")
    
    while True:
        # Get next item from queue
        cursor = db_conn.cursor()
        cursor.execute(
            "SELECT id, file_path FROM processing_queue WHERE status = 'pending' LIMIT 1"
        )
        result = cursor.fetchone()
        
        if result:
            item_id, file_path = result
            # Mark as processing
            cursor.execute(
                "UPDATE processing_queue SET status = 'processing' WHERE id = ?",
                (item_id,)
            )
            db_conn.commit()
            
            try:
                print(f"Processing: {file_path}")
                # Extract text
                text = extract_text(file_path)
                
                # Simple chunking (you can improve this)
                chunks = [text[i:i+4000] for i in range(0, len(text), 3000)]
                
                # Get embeddings
                embeddings = []
                for chunk in chunks:
                    response = client.embeddings.create(
                        input=chunk,
                        model="text-embedding-3-small"
                    )
                    embeddings.append(response.data[0].embedding)
                    # Rate limiting to avoid API limits
                    time.sleep(0.5)
                
                # Store in ChromaDB
                metadata = {"source": file_path, "filename": os.path.basename(file_path)}
                
                collection.add(
                    embeddings=embeddings,
                    documents=chunks,
                    metadatas=[metadata] * len(chunks),
                    ids=[f"{os.path.basename(file_path)}_{i}" for i in range(len(chunks))]
                )
                
                # Mark as completed
                cursor.execute(
                    "UPDATE processing_queue SET status = 'completed' WHERE id = ?",
                    (item_id,)
                )
                db_conn.commit()
                print(f"Processed: {file_path}")
                
            except Exception as e:
                # Mark as failed
                cursor.execute(
                    "UPDATE processing_queue SET status = 'failed' WHERE id = ?",
                    (item_id,)
                )
                db_conn.commit()
                print(f"Error processing {file_path}: {str(e)}")
        
        # Sleep to avoid high CPU usage
        time.sleep(1)

# Main function
def main():
    # Initialize
    db_conn = init_queue_db()
    
    # Initialize OpenAI client - make sure OPENAI_API_KEY is in your environment variables
    openai_client = OpenAI()
    
    # Initialize Chroma client - using persistent storage
    chroma_client = chromadb.PersistentClient(path="./db")
    
    # Start file watcher
    event_handler = PaperHandler(db_conn)
    observer = Observer()
    observer.schedule(event_handler, "research_papers", recursive=True)
    observer.start()
    
    # Start processing thread
    processing_thread = threading.Thread(
        target=process_queue,
        args=(db_conn, openai_client, chroma_client),
        daemon=True
    )
    processing_thread.start()
    
    # Process existing files in directory
    for root, _, files in os.walk("research_papers"):
        for file in files:
            if file.endswith('.pdf'):
                path = os.path.join(root, file)
                cursor = db_conn.cursor()
                try:
                    cursor.execute(
                        "INSERT INTO processing_queue (file_path) VALUES (?)",
                        (path,)
                    )
                    db_conn.commit()
                    print(f"Added existing file to queue: {path}")
                except sqlite3.IntegrityError:
                    pass  # Already in queue
    
    try:
        print("Embedding pipeline started. Press Ctrl+C to stop.")
        print("Monitoring 'research_papers' folder for new PDF files...")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    
    observer.join()

if __name__ == "__main__":
    main()
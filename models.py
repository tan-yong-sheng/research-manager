from sqlalchemy import create_engine, Column, Integer, String, ForeignKey, Table, DateTime, JSON, Boolean, Enum
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime
import enum

Base = declarative_base()

class ProcessingStatus(enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"

# Many-to-many relationship tables
document_tags = Table(
    'document_tags',
    Base.metadata,
    Column('document_id', Integer, ForeignKey('documents.id'), primary_key=True),
    Column('tag_id', Integer, ForeignKey('tags.id'), primary_key=True)
)

document_keywords = Table(
    'document_keywords',
    Base.metadata,
    Column('document_id', Integer, ForeignKey('documents.id'), primary_key=True),
    Column('keyword_id', Integer, ForeignKey('keywords.id'), primary_key=True)
)

class ProcessingQueue(Base):
    __tablename__ = 'processing_queue'
    
    id = Column(Integer, primary_key=True)
    file_path = Column(String, unique=True, nullable=False)
    status = Column(Enum(ProcessingStatus), default=ProcessingStatus.PENDING)
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    error_message = Column(String, nullable=True)
    document_id = Column(Integer, ForeignKey('documents.id'), nullable=True)
    
    # Relationship to document
    document = relationship('Document', back_populates='processing_record')

class Document(Base):
    __tablename__ = 'documents'
    
    id = Column(Integer, primary_key=True)
    title = Column(String, nullable=False)
    filename = Column(String, unique=True, nullable=False)
    authors = Column(String)
    year = Column(Integer)
    abstract = Column(String)
    category = Column(String)
    folder_id = Column(String, nullable=False, default='default')  # References folder UUID
    original_folder_id = Column(String)  # For trash restoration
    upload_date = Column(DateTime, default=datetime.utcnow)
    is_deleted = Column(Boolean, default=False)
    processing_status = Column(Enum(ProcessingStatus), default=ProcessingStatus.PENDING)
    
    # Relationships
    tags = relationship('Tag', secondary=document_tags, back_populates='documents')
    keywords = relationship('Keyword', secondary=document_keywords, back_populates='documents')
    chunks = relationship('DocumentChunk', back_populates='document')
    processing_record = relationship('ProcessingQueue', back_populates='document', uselist=False)

class DocumentChunk(Base):
    __tablename__ = 'document_chunks'
    
    id = Column(Integer, primary_key=True)
    document_id = Column(Integer, ForeignKey('documents.id'), nullable=False)
    chunk_index = Column(Integer, nullable=False)
    content = Column(String, nullable=False)
    chroma_id = Column(String, nullable=False)  # ID in ChromaDB
    embedding_model = Column(String, nullable=False, default='text-embedding-3-small')
    
    # Relationship back to parent document
    document = relationship('Document', back_populates='chunks')

class Tag(Base):
    __tablename__ = 'tags'
    
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)
    documents = relationship('Document', secondary=document_tags, back_populates='tags')

class Keyword(Base):
    __tablename__ = 'keywords'
    
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)
    documents = relationship('Document', secondary=document_keywords, back_populates='documents')

# Create database engine and tables
def init_db():
    engine = create_engine('sqlite:///paper_queue.db')
    Base.metadata.create_all(engine)
    return engine
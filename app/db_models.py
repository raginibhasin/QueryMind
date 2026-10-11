"""
ORM models for QueryMind's OWN application database (metadata store).

This is separate from the "target" databases that users connect to and query
in natural language -- those are read from directly via schema_analyzer.py
and never modeled here.
"""
import datetime
import uuid

from sqlalchemy import (
    Column,
    String,
    Integer,
    Text,
    DateTime,
    ForeignKey,
    Float,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


def _uuid() -> str:
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"

    user_id = Column(String, primary_key=True, default=_uuid)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)
    role = Column(String, default="admin")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    connections = relationship("Connection", back_populates="user", cascade="all, delete-orphan")
    queries = relationship("Query", back_populates="user", cascade="all, delete-orphan")


class Connection(Base):
    __tablename__ = "connections"

    connection_id = Column(String, primary_key=True, default=_uuid)
    user_id = Column(String, ForeignKey("users.user_id"), nullable=False)
    name = Column(String, nullable=False)
    database_type = Column(String, nullable=False)  # 'sqlite' | 'postgresql'
    host = Column(String, nullable=True)
    database_name = Column(String, nullable=False)
    encrypted_credentials = Column(Text, nullable=True)  # JSON blob, Fernet-encrypted
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    user = relationship("User", back_populates="connections")
    schema_entries = relationship("SchemaEntry", back_populates="connection", cascade="all, delete-orphan")


class SchemaEntry(Base):
    """One row per (table, column) discovered by the schema analyzer."""
    __tablename__ = "schemas"

    schema_id = Column(String, primary_key=True, default=_uuid)
    connection_id = Column(String, ForeignKey("connections.connection_id"), nullable=False)
    table_name = Column(String, nullable=False)
    column_name = Column(String, nullable=False)
    data_type = Column(String, nullable=False)
    is_primary_key = Column(Integer, default=0)  # 0/1 boolean
    is_foreign_key = Column(Integer, default=0)
    foreign_key_ref = Column(String, nullable=True)  # "table.column"

    connection = relationship("Connection", back_populates="schema_entries")


class Query(Base):
    __tablename__ = "queries"

    query_id = Column(String, primary_key=True, default=_uuid)
    user_id = Column(String, ForeignKey("users.user_id"), nullable=False)
    connection_id = Column(String, ForeignKey("connections.connection_id"), nullable=False)
    conversation_id = Column(String, nullable=False)  # groups multi-turn follow-ups
    natural_language_query = Column(Text, nullable=False)
    generated_sql = Column(Text, nullable=True)
    execution_time = Column(Float, nullable=True)  # seconds
    status = Column(String, default="pending")  # pending | success | rejected | error
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    user = relationship("User", back_populates="queries")
    result = relationship("QueryResult", back_populates="query", uselist=False, cascade="all, delete-orphan")


class QueryResult(Base):
    __tablename__ = "query_results"

    result_id = Column(String, primary_key=True, default=_uuid)
    query_id = Column(String, ForeignKey("queries.query_id"), nullable=False)
    result_data = Column(Text, nullable=True)  # JSON-encoded rows
    row_count = Column(Integer, default=0)
    chart_type = Column(String, nullable=True)  # 'bar' | 'line' | 'pie' | 'table' | 'metric'
    chart_config = Column(Text, nullable=True)  # JSON-encoded {x_key, y_key, ...}

    query = relationship("Query", back_populates="result")


class SavedQuery(Base):
    __tablename__ = "saved_queries"

    saved_query_id = Column(String, primary_key=True, default=_uuid)
    user_id = Column(String, ForeignKey("users.user_id"), nullable=False)
    connection_id = Column(String, ForeignKey("connections.connection_id"), nullable=False)
    name = Column(String, nullable=False)
    question = Column(Text, nullable=False)
    generated_sql = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

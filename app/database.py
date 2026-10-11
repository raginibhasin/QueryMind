"""
Engine / session setup for QueryMind's own metadata database, plus a helper
to create a live SQLAlchemy engine for a user's TARGET database (the one
they actually want to query in natural language).
"""
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import APP_DATABASE_URL
from app.db_models import Base

engine = create_engine(
    APP_DATABASE_URL,
    connect_args={"check_same_thread": False} if APP_DATABASE_URL.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db():
    """Create all metadata tables if they don't already exist."""
    Base.metadata.create_all(bind=engine)


@contextmanager
def get_session():
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def build_target_engine(database_type: str, database_name: str, host: str = None, credentials: dict = None):
    """
    Build a SQLAlchemy engine for the TARGET database the user wants to run
    natural-language queries against. Kept separate from the app's own DB.

    NOTE: for a real deployment this connection should use a database role
    that only has SELECT privileges on the target database -- the app-level
    validator (sql_validator.py) is a second, independent line of defense,
    not a replacement for that.
    """
    if database_type == "sqlite":
        url = f"sqlite:///{database_name}"
        return create_engine(url, connect_args={"check_same_thread": False})

    if database_type == "postgresql":
        creds = credentials or {}
        user = creds.get("username", "")
        pwd = creds.get("password", "")
        port = creds.get("port", 5432)
        url = f"postgresql+psycopg2://{user}:{pwd}@{host}:{port}/{database_name}"
        return create_engine(url)

    raise ValueError(f"Unsupported database_type: {database_type}")

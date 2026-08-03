"""Database Configuration
========================
SQLAlchemy ORM setup.

Supports:
  - SQLite (default, zero-install, perfect for development)
  - PostgreSQL (recommended for production — e.g. Supabase free tier)
  - MySQL (also supported)

Switching databases only requires changing DATABASE_URL in config.py:
  PostgreSQL: postgresql://user:pass@host:5432/dbname
  MySQL:      mysql+pymysql://user:pass@host:3306/dbname
  SQLite:     sqlite:///./gaokao.db
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from config import DATABASE_URL
from logging_config import get_logger

logger = get_logger("db")

_is_sqlite = DATABASE_URL.startswith("sqlite")

# Build engine kwargs based on database type
_engine_kwargs = {"echo": False}

if _is_sqlite:
    # SQLite needs this for FastAPI's threaded request handling
    _engine_kwargs["connect_args"] = {"check_same_thread": False}
else:
    # PostgreSQL / MySQL: configure connection pool to avoid stale connections
    # and limit concurrent connections (important for free-tier databases)
    _engine_kwargs.update({
        "pool_size": 5,          # base connections kept open
        "max_overflow": 5,       # extra connections under load
        "pool_recycle": 1800,    # recycle connections every 30 min (avoid server timeout)
        "pool_pre_ping": True,   # test connection before use (auto-reconnect)
    })

engine = create_engine(DATABASE_URL, **_engine_kwargs)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """FastAPI dependency: yields a database session and ensures cleanup."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Create all tables. Called once on application startup."""
    Base.metadata.create_all(bind=engine)
    logger.info("[DB] Tables created/verified — engine=%s", DATABASE_URL.split("://")[0])

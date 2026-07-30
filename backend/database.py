"""Database Configuration
========================
SQLAlchemy ORM setup.

Current: SQLite (zero-install, perfect for development)
To switch to MySQL: change DATABASE_URL in config.py to:
    mysql+pymysql://user:password@localhost:3306/gaokao_app
And install pymysql:  pip install pymysql
No other code changes needed.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from config import DATABASE_URL
from logging_config import get_logger

logger = get_logger("db")

# check_same_thread=False: SQLite needs this for FastAPI's threaded request handling
engine = create_engine(
    DATABASE_URL,
    echo=False,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
)

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

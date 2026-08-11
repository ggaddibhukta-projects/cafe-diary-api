from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

import os

# ─── Database Configuration ────────────────────────────────────
# On Render: uses PostgreSQL via DATABASE_URL env var (persistent)
# Locally: uses SQLite file (for dev convenience)

DATABASE_URL = os.environ.get("DATABASE_URL", "")

if DATABASE_URL:
    # Render provides postgres:// but SQLAlchemy needs postgresql://
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    SQLALCHEMY_DATABASE_URL = DATABASE_URL
    engine = create_engine(SQLALCHEMY_DATABASE_URL)
else:
    SQLALCHEMY_DATABASE_URL = "sqlite:///./cafe_diary.db"
    engine = create_engine(
        SQLALCHEMY_DATABASE_URL,
        connect_args={"check_same_thread": False}  # Required for SQLite
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """Dependency that provides a database session per request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

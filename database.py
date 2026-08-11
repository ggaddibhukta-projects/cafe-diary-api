from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

import os

# SQLite database file — use /tmp on Render (ephemeral but writable)
if os.environ.get("RENDER"):
    SQLALCHEMY_DATABASE_URL = "sqlite:////tmp/cafe_diary.db"
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

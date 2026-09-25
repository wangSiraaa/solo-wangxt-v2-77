"""Database engine / session helpers.

DATABASE_URL points at PostgreSQL by default (see README). A test schema or
separate database can be selected via environment variable.
"""
from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

DEFAULT_URL = "postgresql+psycopg2://postgres@127.0.0.1:5432/leakguard"
DATABASE_URL = os.environ.get("DATABASE_URL", DEFAULT_URL)

# SCHEMA env lets the test-suite isolate itself without a second database.
SCHEMA = os.environ.get("APP_SCHEMA")

engine_kwargs: dict = {"future": True, "pool_pre_ping": True}
engine = create_engine(DATABASE_URL, **engine_kwargs)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_session():
    """FastAPI dependency."""
    db = SessionLocal()
    try:
        if SCHEMA:
            db.execute(
                __import__("sqlalchemy").text(f"SET search_path TO {SCHEMA}, public")
            )
        yield db
    finally:
        db.close()

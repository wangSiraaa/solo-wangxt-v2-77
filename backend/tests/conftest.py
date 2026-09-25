"""Pytest fixtures: isolated PostgreSQL schema + seeded demo data."""
from __future__ import annotations

import os
import uuid

os.environ.setdefault("APP_SCHEMA", f"test_{uuid.uuid4().hex[:12]}")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg2://postgres@127.0.0.1:5432/leakguard",
)

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db import engine, SessionLocal
from app.main import app
from app.models import Base
from app.seed import reset_demo

SCHEMA = os.environ["APP_SCHEMA"]


@pytest.fixture(scope="session", autouse=True)
def _schema():
    with engine.begin() as conn:
        conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}"))
        conn.execute(text(f"SET search_path TO {SCHEMA}"))
        Base.metadata.create_all(bind=conn)
    yield
    with engine.begin() as conn:
        conn.execute(text(f"DROP SCHEMA {SCHEMA} CASCADE"))


@pytest.fixture()
def client():
    with TestClient(app) as c:
        db = SessionLocal()
        db.execute(text(f"SET search_path TO {SCHEMA}"))
        reset_demo(db)
        db.close()
        yield c

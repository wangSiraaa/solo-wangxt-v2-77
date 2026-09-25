"""Application configuration.

Storage defaults to PostgreSQL (as required by the task). For unit tests /
local runs without a database server, ``DATABASE_URL=sqlite:///...`` is also
accepted — the ORM models only use portable column types.
"""
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg2://leak:leak@localhost:5432/leakguard",
    )
    allowed_subject_fields: tuple[str, ...] = ("subject_id",)


settings = Settings()

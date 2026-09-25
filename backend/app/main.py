"""FastAPI entry point. Serves API + built Angular static bundle in production."""
from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .db import SCHEMA, engine
from .models import Base
from .routers.api import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    if SCHEMA:
        from sqlalchemy import text

        with engine.begin() as conn:
            conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}"))
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title="LeakGuard - 训练/评测拆分核查服务", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)

DIST = os.environ.get("FRONTEND_DIST", "/workspace/frontend/dist/leakguard/browser")
if os.path.isdir(DIST):
    assets_dir = os.path.join(DIST, "assets")
    if os.path.isdir(assets_dir):
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        index = os.path.join(DIST, "index.html")
        return FileResponse(index)

"""FastAPI application entrypoint. See F007."""

from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.routes import router
from src.api.routes_ingestion import router as ingestion_router

app = FastAPI(title="ATLAS API")

# CORS for the Next.js frontend. Single-user project, no auth layer planned
# (see F007 §2). Port 3001 is the compose-published web port (3000 = Grafana on
# the UGREEN); override via CORS_ALLOW_ORIGINS (comma-separated) for deployment.
_default_origins = "http://localhost:3000,http://localhost:3001"
_origins = [o.strip() for o in os.environ.get("CORS_ALLOW_ORIGINS", _default_origins).split(",")]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_methods=["GET"],
    allow_headers=["*"],
)

app.include_router(router)
app.include_router(ingestion_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}

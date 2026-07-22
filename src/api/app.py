"""FastAPI application entrypoint. See F007."""

from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.routes import router
from src.api.routes_ingestion import router as ingestion_router
from src.logging_config import configure_logging

# Same JSON logging the scheduler and telegram-bot services set up (F029). The api
# service was the one process that never did, so anything it logged below ERROR was
# dropped by the default root level — F078's background download reported nothing on
# success, only on failure. A fire-and-forget task needs to leave a trace either way.
configure_logging()

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

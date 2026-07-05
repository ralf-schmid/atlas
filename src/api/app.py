"""FastAPI application entrypoint. See F007."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.routes import router

app = FastAPI(title="ATLAS API")

# Dev-only CORS for the Next.js dev server. Single-user project, no auth layer
# planned (see F007 §2) — tighten this before any non-localhost deployment.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}

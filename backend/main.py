# FastAPI entry point — wires up routers, CORS, and static file serving
# run with: uvicorn backend.main:app --reload

from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

# load .env from the project root so GEMINI_API_KEY and others are available
try:
    from dotenv import load_dotenv
    _env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    load_dotenv(_env_path)
except ImportError:
    pass

from .application_requisites.routes import analyse, config, evaluate, health, history, scan


# app setup

app = FastAPI(
    title="Affectra",
    description=(
        "Affectra — PII exposure self-check. Centralized App Controller "
        "fans work out to 12 external API compatibility layers and an "
        "Internal API pipeline (source discovery, normalization, "
        "classification, confidence + risk scoring, mitigation, and "
        "response assembly). Every layer is error-safe: a missing key "
        "or unresponsive adapter is logged and the scan continues."
    ),
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# All endpoints live under /api
app.include_router(health.router,    prefix="/api", tags=["meta"])
app.include_router(scan.router,      prefix="/api", tags=["scan"])
app.include_router(config.router,    prefix="/api", tags=["config"])
app.include_router(analyse.router,   prefix="/api", tags=["ai"])
app.include_router(evaluate.router,  prefix="/api", tags=["evaluation"])
app.include_router(history.router,   prefix="/api", tags=["history"])


# static frontend

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_FRONTEND_DIR = os.path.join(_PROJECT_ROOT, "frontend")

if os.path.isdir(_FRONTEND_DIR):
    app.mount(
        "/static",
        StaticFiles(directory=_FRONTEND_DIR),
        name="static",
    )

    @app.get("/", include_in_schema=False)
    def serve_index() -> FileResponse:
        return FileResponse(os.path.join(_FRONTEND_DIR, "index.html"))

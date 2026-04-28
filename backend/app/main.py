"""FastAPI entrypoint — CORS for local Vite dev, health check, generate route.

Live DOCX export uses ``POST /export/docx`` on this app. From the **backend** folder you
edit, run: ``uvicorn app.main:app --reload`` so the UI (e.g. Vite on 5173) hits the same code
as ``scripts/run_real_export_docx_sanity.py`` (watch Uvicorn stdout for ``EXPORT_*_FILE_HIT``).

Optional: set environment variable ``RESUME_TAILOR_PORTFOLIO_DOCX_POLISH=1`` to apply the
Gainwell/Tesla/RWS portfolio DOCX copy pass (see ``app.content.portfolio_resume_polish``)
after the normal export assembly step.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routes.export import router as export_router
from app.routes.gap_analysis import router as gap_analysis_router
from app.routes.generate import router as generate_router
from app.routes.refinery import router as refinery_router

app = FastAPI(title="Resume Tailor API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(generate_router)
app.include_router(export_router)
app.include_router(gap_analysis_router)
app.include_router(refinery_router)


@app.get("/")
def root_health() -> dict:
    return {"status": "ok"}

"""POST /generate — multipart resume + JD + context."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.schemas import GenerateResponse
from app.services.experience_header_normalization import (
    apply_experience_header_normalization_to_resume_data,
)
from app.services.map_requirements import map_requirements_to_resume
from app.services.output_builder import build_output_payload
from app.services.parse_job import clean_job_text, extract_job_signals
from app.services.parse_resume import normalize_resume_structure, parse_resume_docx
from app.services.rewrite_resume import rewrite_resume_bullets
from app.services.scoring import compute_explainable_score
from app.utils.file_io import cleanup_temp_file, save_upload_to_temp

router = APIRouter()


@router.post("/generate", response_model=GenerateResponse)
async def generate(
    resume_file: UploadFile = File(...),
    job_description: str = Form(...),
    context: str = Form(""),
) -> GenerateResponse:
    """
    Day 1 pipeline: temp save → parse → signals → map → rewrite → score → validate response.
    """
    if not job_description.strip():
        raise HTTPException(status_code=400, detail="job_description is required")

    suffix = Path(resume_file.filename or "resume.docx").suffix.lower()
    if suffix and suffix != ".docx":
        raise HTTPException(status_code=400, detail="resume_file must be a .docx file")

    temp_path: Optional[Path] = None
    try:
        temp_path = await save_upload_to_temp(resume_file, suffix=".docx")

        parsed = parse_resume_docx(str(temp_path))
        resume_data = normalize_resume_structure(parsed)
        apply_experience_header_normalization_to_resume_data(resume_data)

        cleaned = clean_job_text(job_description, context)
        # Never fall back to raw JD/context when filtered blob is empty — junk must not re-enter.
        jd_for_signals = cleaned["job_description_filtered"]
        ctx_for_signals = cleaned["context_filtered"] if (context or "").strip() else ""
        job_signals = extract_job_signals(jd_for_signals, context=ctx_for_signals)

        mapping_result = map_requirements_to_resume(resume_data, job_signals)
        rewrite_result = rewrite_resume_bullets(resume_data, mapping_result, job_signals)
        score_result = compute_explainable_score(
            mapping_result, rewrite_result, job_signals
        )

        raw = build_output_payload(
            resume_data, job_signals, mapping_result, rewrite_result, score_result
        )
        # Trust boundary: validate structured output before returning
        return GenerateResponse.model_validate(raw)
    finally:
        cleanup_temp_file(temp_path)

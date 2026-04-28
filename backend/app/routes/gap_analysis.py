"""POST /gap-analysis — capability gap layer (does not invoke DOCX export)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.schemas import GapAnalysisResponse
from app.services.gap_analysis import analyze_resume_gap_report, list_role_template_ids
from app.services.parse_resume import normalize_resume_structure, parse_resume_docx
from app.utils.file_io import cleanup_temp_file, save_upload_to_temp

router = APIRouter(prefix="/gap-analysis", tags=["gap-analysis"])


@router.get("/role-templates")
def list_role_templates() -> Dict[str, List[str]]:
    return {"role_template_ids": list_role_template_ids()}


@router.post("", response_model=GapAnalysisResponse)
async def post_gap_analysis(
    resume_file: UploadFile = File(...),
    role_template: str = Form("product_analyst"),
    job_description: str = Form(""),
) -> GapAnalysisResponse:
    suffix = Path(resume_file.filename or "resume.docx").suffix.lower()
    if suffix and suffix != ".docx":
        raise HTTPException(status_code=400, detail="resume_file must be a .docx file")

    temp_path: Optional[Path] = None
    try:
        temp_path = await save_upload_to_temp(resume_file, suffix=".docx")
        parsed = parse_resume_docx(str(temp_path))
        resume_data = normalize_resume_structure(parsed)
    finally:
        cleanup_temp_file(temp_path)

    try:
        report: Dict[str, Any] = analyze_resume_gap_report(
            resume_data,
            role_template,
            job_description=job_description or "",
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown role_template. Valid ids: {list_role_template_ids()}",
        ) from exc

    return GapAnalysisResponse(
        fit_summary=report["fit_summary"],
        gaps=report["gaps"],
        actions=report["actions"],
        meta=report.get("meta") or {},
    )

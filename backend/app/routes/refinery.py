"""Refinery routes: role-based gap-guided export (does not use Tailor JD rewrite)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from app.services.export_docx import (
    DOCX_EXPORT_VALIDATION_SUCCESS,
    build_export_docx_package,
    split_validation_failure,
)
from app.services.experience_header_normalization import (
    apply_experience_header_normalization_to_resume_data,
)
from app.services.gap_analysis import analyze_resume_gap_report, list_role_template_ids
from app.services.parse_resume import normalize_resume_structure, parse_resume_docx
from app.services.refinery_transform import apply_refinery_actions, build_refinery_export_shims
from app.utils.file_io import cleanup_temp_file, save_upload_to_temp
from app.utils.selected_change_ids import parse_selected_change_ids

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/refinery", tags=["refinery"])

_DEFAULT_ATTACHMENT_NAME = "refinery_resume.docx"


def _latin1_safe_header_value(value: str) -> str:
    s = value or ""
    for bad, good in (
        ("\u2014", "-"),
        ("\u2013", "-"),
        ("\u201c", '"'),
        ("\u201d", '"'),
        ("\u2018", "'"),
        ("\u2019", "'"),
    ):
        s = s.replace(bad, good)
    return s.encode("latin-1", "ignore").decode("latin-1")


def _safe_attachment_filename(name: str) -> str:
    out = _latin1_safe_header_value(name).strip()
    out = out.replace('"', "").replace("\\", "")
    return out if out else _DEFAULT_ATTACHMENT_NAME


@router.post("/export")
async def post_refinery_export(
    resume_file: UploadFile = File(...),
    role_template: str = Form("product_analyst"),
    selected_change_ids: Optional[str] = Form(None),
) -> Response:
    """
    Parse resume, run gap analysis, apply refinery-only bullet merges, then build .docx
    using the same export package as Tailor (neutral rewrite payload; no JD pipeline).
    """
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
        gap_report = analyze_resume_gap_report(
            resume_data,
            role_template,
            job_description="",
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown role_template. Valid ids: {list_role_template_ids()}",
        ) from exc

    refined = apply_refinery_actions(resume_data, gap_report)
    apply_experience_header_normalization_to_resume_data(refined)
    rewrite_result, score_result, mapping_result, job_signals = build_refinery_export_shims(refined)

    pkg_kwargs: dict = {"refinery_experience_spacing": True}
    if selected_change_ids is not None:
        pkg_kwargs["selected_change_ids"] = parse_selected_change_ids(selected_change_ids)
        pkg_kwargs["export_route_label"] = "POST /refinery/export"

    docx_bytes, filename, err, validation_ok = build_export_docx_package(
        refined,
        rewrite_result,
        score_result,
        mapping_result,
        job_signals,
        **pkg_kwargs,
    )
    if err:
        status, checks = split_validation_failure(err)
        raise HTTPException(
            status_code=422,
            detail={"status": status, "checks": checks},
        )
    if not docx_bytes:
        raise HTTPException(status_code=500, detail="Export failed: empty document bytes.")

    ok_msg = validation_ok or DOCX_EXPORT_VALIDATION_SUCCESS
    final_filename = _safe_attachment_filename(filename)
    final_validation = (
        _latin1_safe_header_value(ok_msg).strip()
        or _latin1_safe_header_value(DOCX_EXPORT_VALIDATION_SUCCESS)
    )

    response_headers: dict[str, str] = {
        "Content-Disposition": f'attachment; filename="{final_filename}"',
        "X-Export-Validation": final_validation,
    }
    logger.info(
        "refinery_export boundary: filename=%r validation=%r",
        final_filename,
        final_validation,
    )

    return Response(
        content=docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers=response_headers,
    )

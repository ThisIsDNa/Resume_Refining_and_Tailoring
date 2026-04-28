"""POST /export/docx — same pipeline as /generate; returns recruiter-only .docx."""

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
from app.services.map_requirements import map_requirements_to_resume
from app.services.parse_job import clean_job_text, extract_job_signals
from app.services.parse_resume import normalize_resume_structure, parse_resume_docx
from app.services.rewrite_resume import rewrite_resume_bullets
from app.services.scoring import compute_explainable_score
from app.utils.file_io import cleanup_temp_file, save_upload_to_temp
from app.utils.selected_change_ids import parse_selected_change_ids

logger = logging.getLogger(__name__)

router = APIRouter()

_DEFAULT_ATTACHMENT_NAME = "tailored_resume.docx"


def _latin1_safe_header_value(value: str) -> str:
    """HTTP response header values must be encodable as latin-1 (Starlette/ASGI)."""
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
    # Avoid breaking the quoted filename="..." token in Content-Disposition.
    out = out.replace('"', "").replace("\\", "")
    return out if out else _DEFAULT_ATTACHMENT_NAME


@router.post("/export/docx")
async def export_docx(
    resume_file: UploadFile = File(...),
    job_description: str = Form(...),
    context: str = Form(""),
    selected_change_ids: Optional[str] = Form(None),
) -> Response:
    """
    Run parse → map → rewrite → score, then build a clean .docx (no scoring text inside the file).
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

        cleaned = clean_job_text(job_description, context)
        jd_for_signals = cleaned["job_description_filtered"]
        ctx_for_signals = cleaned["context_filtered"] if (context or "").strip() else ""
        job_signals = extract_job_signals(jd_for_signals, context=ctx_for_signals)

        mapping_result = map_requirements_to_resume(resume_data, job_signals)
        rewrite_result = rewrite_resume_bullets(resume_data, mapping_result, job_signals)
        score_result = compute_explainable_score(
            mapping_result, rewrite_result, job_signals
        )

        pkg_kwargs: dict = {}
        if selected_change_ids is not None:
            pkg_kwargs["selected_change_ids"] = parse_selected_change_ids(selected_change_ids)
            pkg_kwargs["export_route_label"] = "POST /export/docx"

        docx_bytes, filename, err, validation_ok = build_export_docx_package(
            resume_data,
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
            raise HTTPException(
                status_code=500, detail="Export failed: empty document bytes."
            )

        ok_msg = validation_ok or DOCX_EXPORT_VALIDATION_SUCCESS

        # Build response headers once at the boundary; every value must be latin-1 safe.
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
            "export_docx boundary: raw_filename_from_package=%r -> final_filename=%r",
            filename,
            final_filename,
        )
        logger.info("export_docx boundary: response_headers=%r", response_headers)
        for _hk, _hv in response_headers.items():
            if any(ch in _hv for ch in ("\u2014", "\u2013", "\u201c", "\u201d", "\u2018", "\u2019")):
                logger.error(
                    "export_docx boundary: unicode punctuation still present in header %s",
                    _hk,
                )
            _hv.encode("latin-1")

        return Response(
            content=docx_bytes,
            media_type=(
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            ),
            headers=response_headers,
        )
    finally:
        cleanup_temp_file(temp_path)

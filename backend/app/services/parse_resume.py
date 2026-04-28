"""Resume parsing (Day 1: real docx paragraph read + safe fallback)."""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

_SECTION_SEGMENTATION_DEBUG_ENV = "RESUME_TAILOR_SECTION_SEGMENTATION_DEBUG"

# Lines that must never be treated as experience bullets (contact, URLs, section titles).
_SECTION_HEADER_ONLY = re.compile(
    r"(?i)^(experience|work\s*experience|employment|work\s*history|professional\s*experience|"
    r"education|skills|projects?|summary|contact|objective|certifications?|"
    r"references?|portfolio)\s*:?\s*$"
)


def line_is_experience_noise(line: str) -> bool:
    """True if this line belongs in header/skills/summary — not under EXPERIENCE."""
    s = (line or "").strip()
    if len(s) < 2:
        return True
    # Strip common list markers so "• EXPERIENCE" is treated like a section title, not a bullet.
    s = re.sub(r"^[\s•\-\*\u2022\u25cf]+", "", s).strip()
    if len(s) < 2:
        return True
    # Partitioning needs canonical section headings in the tail; do not strip them as noise.
    if detect_resume_section_heading(s) is not None:
        return False
    if _SECTION_HEADER_ONLY.match(s):
        return True
    if re.search(r"[\w.%-]+@[\w.-]+\.\w{2,}", s):
        return True
    if re.search(r"linkedin\.com|github\.com|https?://", s, re.I):
        return True
    if re.search(
        r"(?:\+?\d{1,3}[\s.\-]?)?(?:\(\d{3}\)|\d{3})[\s.\-]?\d{3}[\s.\-]?\d{4}\b",
        s,
    ):
        return True
    return False


def _strip_leading_list_markers(line: str) -> str:
    s = (line or "").strip()
    return re.sub(r"^[\s•\-\*\u2022\u25cf]+", "", s).strip()


def _section_segmentation_debug_enabled() -> bool:
    return (os.environ.get(_SECTION_SEGMENTATION_DEBUG_ENV) or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def emit_section_segmentation_debug(
    line: str, detected_section: str, classification: str
) -> None:
    """Structured log when ``RESUME_TAILOR_SECTION_SEGMENTATION_DEBUG`` is enabled."""
    if not _section_segmentation_debug_enabled():
        return
    logger.info(
        "SECTION_SEGMENTATION_DEBUG %s",
        json.dumps(
            {
                "line": (line or "")[:500],
                "detected_section": detected_section,
                "classification": classification,
            },
            ensure_ascii=False,
        ),
    )


def detect_resume_section_heading(line: str) -> Optional[str]:
    """
    Return a canonical section label for a **standalone** heading line, else ``None``.

    Used for DOCX tail partitioning and experience bullet-stream filtering.
    """
    s = _strip_leading_list_markers(line)
    if len(s) < 2:
        return None
    # More specific patterns first (full-line anchors).
    if re.match(
        r"(?i)^(professional\s+experience|work\s+experience|relevant\s+experience|"
        r"employment(\s+history)?|work\s+history|experience)\s*:?\s*$",
        s,
    ):
        return "EXPERIENCE"
    if re.match(r"(?i)^(selected\s+)?projects?\s*:?\s*$", s):
        return "PROJECTS"
    if re.match(
        r"(?i)^(education|academic(\s+background)?|qualifications?)\s*:?\s*$", s
    ):
        return "EDUCATION"
    if re.match(
        r"(?i)^(certifications?|certificates|licenses(\s+&\s+certifications)?)\s*:?\s*$",
        s,
    ):
        return "CERTIFICATIONS"
    if re.match(
        r"(?i)^(technical\s+skills|core\s+competencies|key\s+skills|competencies|"
        r"skills?)\s*:?\s*$",
        s,
    ):
        return "SKILLS"
    if re.match(
        r"(?i)^(summary|professional\s+summary|executive\s+summary|profile|about\s+me|"
        r"objective)\s*:?\s*$",
        s,
    ):
        return "SUMMARY"
    return None


def lines_include_explicit_experience_heading(lines: Sequence[str]) -> bool:
    return any(detect_resume_section_heading(ln) == "EXPERIENCE" for ln in lines)


def _is_tail_line_candidate(line: str) -> bool:
    """Keep typical body lines; always keep short canonical section headings (e.g. ``SKILLS``)."""
    s = (line or "").strip()
    if len(s) < 2:
        return False
    if len(s) > 8:
        return True
    return detect_resume_section_heading(s) is not None


def partition_tail_lines_by_resume_sections(
    lines: Sequence[str],
) -> Tuple[
    List[str],
    List[str],
    List[str],
    List[str],
    List[str],
    List[str],
]:
    """
    Split a monolithic paragraph / bullet tail into section buckets.

    When no explicit **EXPERIENCE** heading appears anywhere, returns
    ``(list(lines), [], [], [], [], [])`` — legacy behavior (entire tail is experience input).

    When an EXPERIENCE heading exists, only lines while ``current_section == EXPERIENCE``
    appear in the first list; other sections populate the parallel lists in document order.
    """
    seq = [str(x).strip() for x in lines if str(x).strip()]
    if not seq or not lines_include_explicit_experience_heading(seq):
        for ln in seq:
            emit_section_segmentation_debug(
                ln, "LEGACY", "legacy_passthrough_no_explicit_experience_heading"
            )
        return (list(seq), [], [], [], [], [])

    current = "OUTSIDE"
    exp: List[str] = []
    proj: List[str] = []
    edu: List[str] = []
    cert: List[str] = []
    sk: List[str] = []
    sum_x: List[str] = []

    for ln in seq:
        hit = detect_resume_section_heading(ln)
        if hit:
            current = hit
            emit_section_segmentation_debug(
                ln, hit, "section_boundary_heading_consumed"
            )
            continue
        emit_section_segmentation_debug(ln, current, f"body_in_{current}")
        if current == "EXPERIENCE":
            exp.append(ln)
        elif current == "PROJECTS":
            proj.append(ln)
        elif current == "EDUCATION":
            edu.append(ln)
        elif current == "CERTIFICATIONS":
            cert.append(ln)
        elif current == "SKILLS":
            sk.append(ln)
        elif current == "SUMMARY":
            sum_x.append(ln)
        else:
            sum_x.append(ln)
    return (exp, proj, edu, cert, sk, sum_x)


def experience_lines_for_identity_segmentation(lines: Sequence[str]) -> List[str]:
    """Experience-only lines for ``_segment_bullets_into_entries`` (defense in depth)."""
    exp, _, _, _, _, _ = partition_tail_lines_by_resume_sections(lines)
    return exp


def _lines_to_project_rows(project_lines: List[str]) -> List[Dict[str, Any]]:
    if not project_lines:
        return []
    return [
        {
            "name": project_lines[0],
            "subtitle": "",
            "bullets": project_lines[1:],
        }
    ]


def _lines_to_education_rows(edu_lines: List[str]) -> List[Dict[str, Any]]:
    if not edu_lines:
        return []
    return [
        {
            "degree": edu_lines[0],
            "institution": "",
            "date_range": "",
            "location": "",
            "bullets": edu_lines[1:],
        }
    ]


def _lines_to_certification_rows(cert_lines: List[str]) -> List[Dict[str, Any]]:
    if not cert_lines:
        return []
    return [
        {
            "name": cert_lines[0],
            "issuer": "",
            "date_range": "",
            "bullets": cert_lines[1:],
        }
    ]


def parse_resume_docx(file_path: str) -> dict:
    """
    Parse a .docx resume into a loose dict structure.

    Day 2: integrate structural normalization, section detection, and building_blocks helpers.
    """
    path = Path(file_path)
    meta = {"source_filename": path.name, "format": "docx"}

    try:
        from docx import Document  # python-docx

        doc = Document(file_path)
        paragraphs: List[str] = []
        for p in doc.paragraphs:
            text = (p.text or "").strip()
            if text:
                paragraphs.append(text)
        return {
            **meta,
            "raw_paragraphs": paragraphs,
            "parse_ok": True,
            "body_text": "\n".join(paragraphs),
        }
    except Exception:
        # TODO: Day 2 — structured logging, richer error typing, partial recovery
        return {
            **meta,
            "raw_paragraphs": [],
            "parse_ok": False,
            "body_text": "",
            "error": "docx_parse_failed",
        }


def normalize_resume_structure(parsed_doc: dict) -> dict:
    """
    Map raw parse output into a stable resume_data shape for downstream services.

    Populates ``raw_text`` and ``sections`` for the requirement-mapping layer; keeps
    legacy ``summary`` / ``raw`` for compatibility.
    """
    body = parsed_doc.get("body_text") or ""
    paragraphs: List[str] = list(parsed_doc.get("raw_paragraphs") or [])
    summary = ""
    if body:
        first = body.split("\n", 1)[0].strip()
        summary = first[:500]

    if paragraphs:
        head = paragraphs[0].strip() if paragraphs else ""
        tail = [p.strip() for p in paragraphs[1:] if _is_tail_line_candidate(p)]
        tail = [p for p in tail if not line_is_experience_noise(p)]
    else:
        head = summary
        tail = [ln.strip() for ln in body.split("\n")[1:] if _is_tail_line_candidate(ln)]
        tail = [p for p in tail if not line_is_experience_noise(p)]

    exp_lines, proj_lines, edu_lines, cert_lines, skill_lines, sum_extra = (
        partition_tail_lines_by_resume_sections(tail)
    )

    summary_parts: List[str] = []
    if head:
        summary_parts.append(head)
    elif summary:
        summary_parts.append(summary)
    summary_parts.extend(sum_extra)
    summary_list = [s for s in summary_parts if (s or "").strip()]

    sections: Dict[str, Any] = {
        "summary": summary_list,
        "experience": [
            {
                "company": "",
                "title": "",
                "date_range": "",
                "bullets": exp_lines,
            }
        ],
        "skills": list(skill_lines),
        "education": _lines_to_education_rows(edu_lines),
        "certifications": _lines_to_certification_rows(cert_lines),
        "projects": _lines_to_project_rows(proj_lines),
    }

    return {
        "meta": {
            "source_filename": parsed_doc.get("source_filename"),
            "parse_ok": parsed_doc.get("parse_ok", False),
        },
        "summary": summary,
        "raw_text": body,
        "sections": sections,
        "experience": [],
        "skills": [],
        "education": [],
        "raw": parsed_doc,
    }

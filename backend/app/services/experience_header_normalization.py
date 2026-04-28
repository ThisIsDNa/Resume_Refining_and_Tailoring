"""
Leading experience ``bullets`` sometimes contain location + date lines that belong in
header fields. This pass promotes only a clear first-pair at indices 0–1 when metadata
slots are still empty (export / generate plumbing — not gap-engine logic).
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

from app.services.resume_document_assembly import (
    _line_is_compact_location_metadata,
    _line_is_standalone_calendar_date_range,
    _normalize_resume_line_dashes,
)

logger = logging.getLogger(__name__)
_HEADER_NORMALIZATION_DEBUG_ENV = "RESUME_TAILOR_HEADER_NORMALIZATION_DEBUG"


def _log_header_normalization_debug(
    *,
    entry_index: int,
    company: str,
    original_order: List[str],
    normalized: str,
) -> None:
    if (os.environ.get(_HEADER_NORMALIZATION_DEBUG_ENV) or "").strip().lower() not in (
        "1",
        "true",
        "yes",
        "on",
    ):
        return
    logger.debug(
        "header normalization applied: %s",
        json.dumps(
            {
                "entry_index": entry_index,
                "company": (company or "").strip()[:200],
                "original_order": original_order,
                "normalized": normalized[:260],
            },
            ensure_ascii=False,
        ),
    )


def _valid_job_identity(nb: Dict[str, Any]) -> bool:
    co = str(nb.get("company") or "").strip()
    ro = str(nb.get("title") or nb.get("role") or "").strip()
    return bool(co) and bool(ro)


def _normalize_experience_headers(experience_blocks: List[dict]) -> List[dict]:
    """
    If the first two ``bullets`` are exclusively a location line and a calendar date span
    (either order), move them into ``location`` / ``date_range`` + ``date`` and drop them
    from ``bullets``. Requires empty existing location and date header fields and valid
    company + role. Otherwise leaves the block unchanged.
    """
    out: List[dict] = []
    for bi, block in enumerate(experience_blocks or []):
        if not isinstance(block, dict):
            out.append(block)
            continue
        nb = dict(block)
        raw_bullets = nb.get("bullets") or []
        if not isinstance(raw_bullets, list) or len(raw_bullets) < 2:
            out.append(nb)
            continue
        if not _valid_job_identity(nb):
            out.append(nb)
            continue
        loc_f = str(nb.get("location") or "").strip()
        date_f = str(nb.get("date_range") or nb.get("date") or "").strip()
        if loc_f or date_f:
            out.append(nb)
            continue

        a = _normalize_resume_line_dashes(str(raw_bullets[0]).strip())
        b = _normalize_resume_line_dashes(str(raw_bullets[1]).strip())
        if not a or not b:
            out.append(nb)
            continue

        loc_s: Optional[str] = None
        date_s: Optional[str] = None
        order: List[str] = []
        if _line_is_compact_location_metadata(a) and _line_is_standalone_calendar_date_range(b):
            loc_s, date_s = a, b
            order = ["location", "date"]
        elif _line_is_standalone_calendar_date_range(a) and _line_is_compact_location_metadata(b):
            date_s, loc_s = a, b
            order = ["date", "location"]
        else:
            out.append(nb)
            continue

        nb["location"] = loc_s.strip()
        dval = date_s.strip()
        nb["date_range"] = dval
        nb["date"] = dval
        nb["bullets"] = [str(x).strip() for x in raw_bullets[2:] if str(x).strip()]
        norm_display = f"{dval} | {loc_s.strip()}"
        _log_header_normalization_debug(
            entry_index=bi,
            company=str(nb.get("company") or ""),
            original_order=order,
            normalized=norm_display,
        )
        out.append(nb)
    return out


def apply_experience_header_normalization_to_resume_data(resume_data: dict) -> None:
    """In-place: normalize ``sections.experience`` when present."""
    sections = resume_data.get("sections")
    if not isinstance(sections, dict):
        return
    exp = sections.get("experience")
    if not isinstance(exp, list):
        return
    sections["experience"] = _normalize_experience_headers(exp)

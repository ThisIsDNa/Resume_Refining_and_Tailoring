"""Gap analysis: grounded resume signals vs role templates (no DOCX coupling)."""

from __future__ import annotations

from app.services.gap_analysis.gap_engine import analyze_resume_gap_report
from app.services.gap_analysis.role_templates import get_role_profile, list_role_template_ids
from app.services.gap_analysis.signal_extractor import extract_resume_signals

__all__ = [
    "analyze_resume_gap_report",
    "extract_resume_signals",
    "get_role_profile",
    "list_role_template_ids",
]

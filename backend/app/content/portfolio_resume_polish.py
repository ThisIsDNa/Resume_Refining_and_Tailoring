"""
Controlled DOCX copy for the Gainwell / Tesla / RWS portfolio resume.

Projects are **declared** here (structured ``ProjectEntry`` rows), not inferred from raw
text or segmentation. No parsing-based project extraction is used on this path.

Enable at runtime with::

    RESUME_TAILOR_PORTFOLIO_DOCX_POLISH=1

Applied only when the assembled payload matches a narrow fingerprint (three employers
in order). Does not alter segmentation or upstream parsing for other resumes.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Dict, List, Tuple

from app.services.resume_document_assembly import (
    CertificationEntry,
    ExperienceEntry,
    ProjectEntry,
    ResumeDocumentPayload,
)

logger = logging.getLogger(__name__)
PORTFOLIO_DOCX_POLISH_SUMMARY = (
    "Senior Business Systems Analyst / UAT Lead who specializes in stabilizing ambiguous, "
    "high-risk systems by building structured validation frameworks and driving stakeholder "
    "alignment across enterprise environments."
)

PORTFOLIO_DOCX_POLISH_SOURCE = "portfolio_docx_polish_v4"

_SERVICE_NOW_CERT = "ServiceNow Certified System Administrator"

_GAINWELL = ExperienceEntry(
    company="Gainwell Technologies",
    role="Senior Business Systems Analyst / Senior UAT Lead",
    location="Remote",
    date="April 2024 – Present",
    bullets=[
        "Stabilized a failing SLA pipeline by resolving 50+ overdue deliverables, reverse engineering "
        "undocumented CRM workflows, and rebuilding client approval processes from scratch.",
        "Led end-to-end validation for Medi-Cal Dental modernization initiatives, including a "
        "high-traffic Provider Portal supporting enrollment, eligibility, and transactional workflows.",
        "Coordinated cross-functional teams across business, engineering, and QA to ensure deliverables "
        "met client expectations under tight timelines.",
        "Operated as functional SME across Dynamics 365 CRM, Essette, and GIA systems, translating "
        "ambiguous requirements into structured test frameworks and scalable solutions.",
        "Worked within ambiguous, undocumented environments to define requirements, structure test plans, "
        "and drive initiatives to production readiness.",
        "Facilitated client-facing validation walkthroughs and drove approval of high-visibility deliverables.",
        "Developed automation tools using Selenium and Python to validate client-facing workflows, "
        "reducing manual effort and improving release readiness.",
    ],
)

_TESLA = ExperienceEntry(
    company="Tesla",
    role="Data Specialist (Autopilot)",
    location="San Mateo, CA",
    date="July 2020 – June 2022",
    bullets=[
        "Partnered cross-functionally to validate camera and sensor datasets, identifying systemic "
        "quality gaps and improving data reliability for downstream model performance.",
        "Reduced rework by 90% by standardizing test scripts and validation workflows, improving "
        "operational efficiency across data review processes.",
        "Supported large-scale Autopilot data validation in a production environment, ensuring "
        "dataset integrity and real-world accuracy.",
        "Contributed to operational improvements in high-impact autonomy initiatives requiring "
        "precision and scalability.",
    ],
)

_RWS = ExperienceEntry(
    company="RWS Moravia (Client: Apple)",
    role="Business Data Technician",
    location="Sunnyvale, CA",
    date="June 2019 – June 2020",
    bullets=[
        "Validated and optimized geospatial data workflows supporting Apple Maps, improving data "
        "accuracy and maintaining strict production quality standards.",
        "Increased mapping data accuracy through structured validation and error correction processes.",
        "Reduced processing time by improving workflow efficiency and data handling procedures.",
        "Maintained strong production adherence in a deadline-driven environment.",
    ],
)

# Single explicit portfolio project (name + bullets only; no dates, no edu/cert/skills text).
_AI_UAT_PROJECT = ProjectEntry(
    name="AI UAT Copilot | github.com/ThisIsDNa/ai-uat-copilot",
    subtitle="",
    bullets=[
        "Built an AI-driven testing assistant that converts unstructured requirements into structured "
        "test cases, validation steps, and review-ready outputs, improving QA consistency and reducing manual effort.",
    ],
)

# Declared project list for the portfolio polish path (max two bullets per project by policy).
PORTFOLIO_DECLARED_PROJECTS: Tuple[ProjectEntry, ...] = (_AI_UAT_PROJECT,)


def _portfolio_employer_match_blob(ent: ExperienceEntry) -> str:
    """Lowercase text used to match employer tokens (company first; include role as fallback)."""
    return f"{(ent.company or '').strip()} {(ent.role or '').strip()}".strip().lower()


def _portfolio_fingerprint_eval(
    payload: ResumeDocumentPayload,
) -> Tuple[bool, List[str], List[str], List[str], Dict[str, object]]:
    """
    True when there are ≥3 experience rows and ordered hits for Gainwell → Tesla → RWS
    (substring match on employer blob), not necessarily at indices 0,1,2.
    """
    exp: List[ExperienceEntry] = list(payload.experience or [])
    companies = [(e.company or "").strip() for e in exp]
    normalized = [c.lower() for c in companies]
    blobs = [_portfolio_employer_match_blob(e) for e in exp]
    i_g = next((i for i, b in enumerate(blobs) if "gainwell" in b), -1)
    i_t = next((i for i, b in enumerate(blobs) if i > i_g and "tesla" in b), -1)
    i_r = next((i for i, b in enumerate(blobs) if i > i_t and "rws" in b), -1)
    ok = len(exp) >= 3 and i_g >= 0 and i_t >= 0 and i_r >= 0
    meta: Dict[str, object] = {
        "indices_gainwell": i_g,
        "indices_tesla": i_t,
        "indices_rws": i_r,
        "entry_count": len(exp),
    }
    return ok, companies, normalized, blobs, meta


def _log_portfolio_fingerprint_debug(
    *,
    env_gate: bool,
    fingerprint_match: bool,
    companies: List[str],
    normalized: List[str],
    blobs: List[str],
    meta: Dict[str, object],
) -> None:
    if not env_gate:
        return
    payload = json.dumps(
        {
            "env_gate": env_gate,
            "fingerprint_match": fingerprint_match,
            "companies": companies,
            "normalized_company_names": normalized,
            "employer_match_blobs": blobs,
            **meta,
        },
        ensure_ascii=False,
    )
    logger.debug("portfolio fingerprint: %s", payload)


def _ensure_servicenow_certification(payload: ResumeDocumentPayload) -> None:
    rows = list(payload.certifications or [])
    target = _SERVICE_NOW_CERT.strip().lower()
    if any((r.name or "").strip().lower() == target for r in rows):
        payload.certifications = rows
        return
    rows.append(CertificationEntry(name=_SERVICE_NOW_CERT, issuer="", date="", bullets=[]))
    payload.certifications = rows


def maybe_apply_portfolio_resume_polish(payload: ResumeDocumentPayload) -> bool:
    """
    Replace summary, experience bullets, Tesla/RWS headers, projects, and ServiceNow cert placement
    for the fingerprinted portfolio resume only.
    """
    env_gate = os.environ.get("RESUME_TAILOR_PORTFOLIO_DOCX_POLISH", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    fp_ok, companies, normalized, blobs, meta = _portfolio_fingerprint_eval(payload)
    _log_portfolio_fingerprint_debug(
        env_gate=env_gate,
        fingerprint_match=fp_ok,
        companies=companies,
        normalized=normalized,
        blobs=blobs,
        meta=meta,
    )
    if not env_gate:
        return False
    if not fp_ok:
        return False
    payload.summary = PORTFOLIO_DOCX_POLISH_SUMMARY
    payload.summary_source = PORTFOLIO_DOCX_POLISH_SOURCE
    payload.experience = [_GAINWELL, _TESLA, _RWS]
    payload.projects = [
        ProjectEntry(p.name, p.subtitle, list(p.bullets or [])[:2]) for p in PORTFOLIO_DECLARED_PROJECTS
    ]
    _ensure_servicenow_certification(payload)
    logger.info("portfolio DOCX polish applied")
    return True

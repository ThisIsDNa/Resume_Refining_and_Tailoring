"""
Real DOCX export sanity: ``build_export_docx_package`` → python-docx parse of bytes.

- Does **not** import unittest or ``tests.*`` fixtures.
- Default: self-contained resume payload (same shape as production ``resume_data``).
- Optional: ``python run_real_export_docx_sanity.py C:\\path\\to\\resume.docx`` runs
  parse → normalize → map → rewrite → score → export (same as POST /export/docx).
"""

from __future__ import annotations

import argparse
import re
import sys
from io import BytesIO
from pathlib import Path

from docx import Document

# Run as ``python scripts/run_real_export_docx_sanity.py`` from backend/
if __name__ == "__main__":
    _backend = Path(__file__).resolve().parent.parent
    if str(_backend) not in sys.path:
        sys.path.insert(0, str(_backend))


def _docx_paragraphs(docx_bytes: bytes) -> list[str]:
    doc = Document(BytesIO(docx_bytes))
    return [p.text.strip() for p in doc.paragraphs if p.text.strip()]


def _section_slice(lines: list[str], start: str, stop: str | None) -> list[str]:
    u = [x.upper() for x in lines]
    try:
        i0 = u.index(start.upper())
    except ValueError:
        return []
    i1 = len(lines)
    if stop:
        try:
            i1 = u.index(stop.upper())
        except ValueError:
            i1 = len(lines)
    return lines[i0 + 1 : i1]


def _golden_resume_data() -> dict:
    """Structured resume dict only (not loaded from tests/)."""
    raw_text = "\n".join(
        [
            "Jane Doe",
            "jane@example.com | 555-0100",
            "",
            "Senior Business Systems Analyst Senior UAT Lead Gainwell Tesla RWS Moravia",
            "user acceptance testing regulatory compliance enterprise cross-functional",
            "business analysis stakeholder management data quality project delivery",
            "Led UAT for Provider Portal.",
            "Supported Autopilot data pipelines.",
            "Maintained localization data workflows.",
            "Systems & Platforms: Azure, Jira",
            "Data & Analytics: SQL, Power BI",
            "Testing & Governance: SLA Management, QA",
            "Documentation & Modeling: BRD, process maps",
            "Bachelor of Science in Computer Science from State University",
            "CBAP IIBA certification",
            "PMI-ACP certification program",
        ]
    )
    experience = [
        {
            "company": "Gainwell Technologies",
            "title": "Senior Business Systems Analyst / Senior UAT Lead",
            "date_range": "April 2024 – Present",
            "location": "Remote",
            "bullets": ["Led UAT for Provider Portal."],
        },
        {
            "company": "Tesla",
            "title": "Data Specialist (Autopilot)",
            "date_range": "July 2020 – June 2022",
            "location": "San Mateo, CA",
            "bullets": ["Supported Autopilot data pipelines."],
        },
        {
            "company": "RWS Moravia (Client: Apple)",
            "title": "Business Data Technician",
            "date_range": "June 2019 – June 2020",
            "location": "Sunnyvale, CA",
            "bullets": ["Maintained localization data workflows."],
        },
    ]
    projects = [
        {
            "name": "Personal Project — Analytics Dashboard",
            "subtitle": "",
            "bullets": [
                "Built prototype using React and API integration.",
                "Education: MBA, Metro College",
                "Certifications: PMI-ACP — 2021",
                "Documentation & Modeling: process maps for portfolio",
            ],
        }
    ]
    education = [
        {
            "degree": "B.S. Computer Science",
            "institution": "State University",
            "date": "2014",
            "location": "",
            "bullets": [],
        }
    ]
    certifications = [
        {
            "name": "Certified Business Analysis Professional",
            "issuer": "IIBA",
            "date": "2018",
            "bullets": [],
        }
    ]
    skills = ["Data & Analytics: SQL, Power BI"]
    return {
        "raw_text": raw_text,
        "sections": {
            "experience": experience,
            "projects": projects,
            "education": education,
            "certifications": certifications,
            "skills": skills,
        },
    }


def _pipeline_inputs():
    jd = (
        "Lead cross-functional teams to deliver enterprise software solutions "
        "with regulatory compliance and documented validation."
    )
    job_signals = {"validated_requirements": [jd]}
    mapping_result = {
        "requirement_matches": [
            {
                "requirement_text": jd,
                "classification": "strong",
                "priority": "nice_to_have",
                "matched_evidence": [{"id": "e1"}],
            }
        ]
    }
    score_result = {"overall_score": 65, "summary": {"matched_requirements": 4}}
    rewrite_result: dict = {"bullet_changes": [], "tailored_summary": ""}
    return score_result, mapping_result, job_signals, rewrite_result


def _export_from_docx_path(path: Path) -> tuple[bytes, str | None]:
    from app.services.export_docx import build_export_docx_package
    from app.services.map_requirements import map_requirements_to_resume
    from app.services.parse_job import clean_job_text, extract_job_signals
    from app.services.parse_resume import normalize_resume_structure, parse_resume_docx
    from app.services.rewrite_resume import rewrite_resume_bullets
    from app.services.scoring import compute_explainable_score

    jd = (
        "Lead cross-functional teams to deliver enterprise software solutions "
        "with regulatory compliance and documented validation."
    )
    context = ""
    parsed = parse_resume_docx(str(path))
    resume_data = normalize_resume_structure(parsed)
    cleaned = clean_job_text(jd, context)
    jd_f = cleaned["job_description_filtered"]
    ctx_f = cleaned["context_filtered"] if (context or "").strip() else ""
    job_signals = extract_job_signals(jd_f, context=ctx_f)
    mapping_result = map_requirements_to_resume(resume_data, job_signals)
    rewrite_result = rewrite_resume_bullets(resume_data, mapping_result, job_signals)
    score_result = compute_explainable_score(mapping_result, rewrite_result, job_signals)
    docx_bytes, filename, err, ok = build_export_docx_package(
        resume_data, rewrite_result, score_result, mapping_result, job_signals
    )
    if err:
        return b"", err
    if not docx_bytes:
        return b"", "empty docx bytes"
    return docx_bytes, None


def _export_from_golden() -> tuple[bytes, str | None]:
    from app.services.export_docx import build_export_docx_package

    resume_data = _golden_resume_data()
    score_result, mapping_result, job_signals, rewrite_result = _pipeline_inputs()
    docx_bytes, filename, err, ok = build_export_docx_package(
        resume_data, rewrite_result, score_result, mapping_result, job_signals
    )
    if err:
        return b"", err
    if not docx_bytes:
        return b"", "empty docx bytes"
    return docx_bytes, None


def main() -> int:
    parser = argparse.ArgumentParser(description="Real DOCX export sanity (no unittest).")
    parser.add_argument(
        "resume_docx",
        nargs="?",
        default=None,
        help="Optional path to a real resume .docx (full parse→export pipeline)",
    )
    args = parser.parse_args()

    if args.resume_docx:
        p = Path(args.resume_docx)
        if not p.is_file():
            print(f"FAIL: file not found: {p}", file=sys.stderr)
            return 2
        print(f"Using resume file: {p.resolve()}")
        docx_bytes, err = _export_from_docx_path(p)
    else:
        print("No .docx path passed — using self-contained golden resume_data (still real export code path).")
        docx_bytes, err = _export_from_golden()

    if err:
        print(f"FAIL: export error: {err}", file=sys.stderr)
        return 1

    lines = _docx_paragraphs(docx_bytes)
    joined = "\n".join(lines)
    try:
        i_sum = [x.upper() for x in lines].index("SUMMARY")
        summary_text = lines[i_sum + 1] if i_sum + 1 < len(lines) else ""
    except ValueError:
        summary_text = ""

    print("\n=== SUMMARY (first paragraph after SUMMARY heading) ===")
    print(summary_text)

    forbidden = re.compile(
        r"(?i)^professional\s+with\s+experience\s+in\s+excel,\s+power\s+bi,\s+and\s+python\.?$"
    )
    errors: list[str] = []

    if forbidden.match(summary_text.strip()) or "excel, power bi, and python" in summary_text.lower():
        errors.append('Summary must not be the weak "Professional with experience in excel, power bi, and python." pattern.')

    identity = re.compile(
        r"(?i)(business\s+systems?\s+analyst|bsa|\buat\b|user\s+acceptance)",
    )
    systems = re.compile(r"(?i)(system|systems|enterprise|validation|regulated|compliance)")
    if not identity.search(summary_text):
        errors.append("Summary should reflect Senior BSA / UAT identity (no match).")
    if not systems.search(summary_text):
        errors.append("Summary should reflect systems / validation / enterprise work (no match).")

    proj_body = "\n".join(_section_slice(lines, "PROJECTS", "EDUCATION")).lower()
    print("\n=== PROJECTS section (body only, lowercased) ===")
    print(proj_body or "(empty)")

    if re.search(r"(?i)\b(?:bachelor|master|b\.?s\.?|m\.?b\.?a\.?|mba|ph\.?d\.?)\b", proj_body):
        errors.append("Personal Project must not contain degree lines.")
    if re.search(
        r"(?i)\b(?:certification|certificate|pmi-?acp|cbap|iiba|comptia|aws\s+certified)\b",
        proj_body,
    ):
        errors.append("Personal Project must not contain certification-style lines.")
    if "education:" in proj_body or "certifications:" in proj_body:
        errors.append("Personal Project must not contain Education:/Certifications: leak labels.")
    if "documentation & modeling:" in proj_body or "testing & governance:" in proj_body:
        errors.append("Personal Project must not contain skill-bucket category lines.")
    if "react" not in proj_body:
        errors.append("Expected at least one real project bullet (e.g. React) under PROJECTS.")

    print("\n=== RESULT ===")
    if errors:
        for e in errors:
            print(f"FAIL: {e}")
        return 1
    print("PASS: summary is strong/identity-aligned; Personal Project is project-only.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

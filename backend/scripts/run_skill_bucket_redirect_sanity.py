"""
Sanity: grouped skill-bucket lines must leave bullet lists and merge into skills before validation.

Run from the backend directory:
  python scripts/run_skill_bucket_redirect_sanity.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.resume_document_assembly import (  # noqa: E402
    ResumeDocumentPayload,
    build_resume_document_payload,
    skill_bucket_line_redirects_to_skills,
    validate_resume_document_payload,
)

SKILL_LINES = (
    "Testing & Governance: SLA Management, QA Framework Design, Defect Triage",
    "Systems & Platforms: Dynamics 365 CRM, Essette, GIA, ServiceNow",
    "Documentation & Modeling: Process Mapping, Workflow Design, Requirement Decomposition",
    "Data & Analytics: SQL, Power BI, Tableau, Excel, Python",
)

AFFECTED_EXPERIENCE_BLOCK = {
    "company": "Acme Corp",
    "title": "Business Analyst",
    "date_range": "2020 - Present",
    "bullets": [
        "Owned requirements workshops and traceability matrices.",
        *SKILL_LINES,
    ],
}

PROJECT_WITH_LEAK = {
    "name": "Sample Project",
    "bullets": [
        "Delivered integration milestones.",
        "Testing & Governance: SLA Management, QA Framework Design",
    ],
}


def _print_bullets(label: str, bullets: list[str]) -> None:
    print(f"\n=== {label} ({len(bullets)} lines) ===")
    for i, line in enumerate(bullets):
        print(f"  [{i}] {line}")


def _collect_all_bullet_lines(payload: ResumeDocumentPayload) -> list[tuple[str, str]]:
    """(source_label, line) for every bullet in structured payload."""
    out: list[tuple[str, str]] = []
    for i, e in enumerate(payload.experience):
        for j, b in enumerate(e.bullets):
            out.append((f"experience[{i}].bullets[{j}]", str(b).strip()))
    for i, p in enumerate(payload.projects):
        for j, b in enumerate(p.bullets):
            out.append((f"projects[{i}].bullets[{j}]", str(b).strip()))
        if (p.subtitle or "").strip():
            out.append((f"projects[{i}].subtitle", (p.subtitle or "").strip()))
    for i, ed in enumerate(payload.education):
        for j, b in enumerate(ed.bullets):
            out.append((f"education[{i}].bullets[{j}]", str(b).strip()))
    for i, c in enumerate(payload.certifications):
        for j, b in enumerate(c.bullets):
            out.append((f"certifications[{i}].bullets[{j}]", str(b).strip()))
    return out


def main() -> int:
    print("Skill-bucket redirection sanity check")
    print("=" * 60)

    before_bullets = list(AFFECTED_EXPERIENCE_BLOCK["bullets"])
    _print_bullets("1. Affected experience entry - bullets BEFORE cleanup (raw block)", before_bullets)

    payload = build_resume_document_payload(
        name="Sanity User",
        contact="sanity@example.com",
        summary="Analyst with delivery and tooling experience.",
        summary_source="skill_bucket_sanity",
        experience_blocks=[
            AFFECTED_EXPERIENCE_BLOCK,
            {
                "company": "Other Co",
                "title": "Intern",
                "date_range": "2018 - 2019",
                "bullets": ["Filed tickets."],
            },
        ],
        projects=[PROJECT_WITH_LEAK],
        education=[],
        certifications=[],
        skills=["Agile", "Scrum"],
    )

    # Affected entry = first experience row (Acme)
    after_bullets = list(payload.experience[0].bullets)
    _print_bullets("2. Same entry - bullets AFTER cleanup (payload.experience[0])", after_bullets)

    print("\n=== 3. Final skills payload ===")
    print(json.dumps(payload.skills, ensure_ascii=False, indent=2))

    errors: list[str] = []

    print("\n=== 4. Skill bucket lines must NOT remain in any bullet ===")
    for needle in SKILL_LINES:
        leaked = [lbl for lbl, ln in _collect_all_bullet_lines(payload) if ln == needle]
        if leaked:
            errors.append(f"Still in bullets: {needle!r} at {leaked}")
            print(f"  FAIL: {needle[:48]}... -> {leaked}")
        else:
            print(f"  OK:   absent from bullets - {needle[:56]}...")

    print("\n=== 5. Skill bucket lines MUST appear in skills payload ===")
    skills_set = list(payload.skills)
    for needle in SKILL_LINES:
        if needle not in skills_set:
            errors.append(f"Missing from skills: {needle!r}")
            print(f"  FAIL: not in skills - {needle[:56]}...")
        else:
            print(f"  OK:   in skills - {needle[:56]}...")

    print("\n=== 6. No final bullet/subtitle line matches skill-bucket redirect pattern ===")
    bad: list[tuple[str, str]] = []
    for src, line in _collect_all_bullet_lines(payload):
        if skill_bucket_line_redirects_to_skills(line):
            bad.append((src, line))
    if bad:
        for src, line in bad:
            print(f"  FAIL: {src}: {line[:72]}...")
            errors.append(f"Skill bucket pattern in {src}: {line!r}")
    else:
        print("  OK: no bullet or project subtitle matched skill_bucket_line_redirects_to_skills")

    print("\n=== 7. validate_resume_document_payload (unchanged rules) ===")
    try:
        validate_resume_document_payload(payload)
        print("  OK: validation passed")
    except Exception as exc:  # noqa: BLE001 - surface contract errors clearly
        errors.append(f"Validation failed: {exc}")
        print(f"  FAIL: {exc}")

    print("\n" + "=" * 60)
    if errors:
        print("RESULT: FAILED")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("RESULT: PASSED - skill lines removed from bullets, skills payload complete, no leakage.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

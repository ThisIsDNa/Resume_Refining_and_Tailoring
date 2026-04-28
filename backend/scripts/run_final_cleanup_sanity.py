"""
Final structure sanity: Tesla/RWS identity, project isolation, cert/skills hygiene, grounded summary.

Run from the backend directory:
  python scripts/run_final_cleanup_sanity.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.export_docx import (  # noqa: E402
    _build_grounding_corpus,
    strongest_summary_from_resume,
)
from app.services.resume_document_assembly import (  # noqa: E402
    build_resume_document_payload,
    dict_rows_to_certification_entries,
    experience_entry_header_lines,
    merge_distinct_skill_lines,
    prepare_project_blocks_for_docx,
    skill_bucket_line_redirects_to_skills,
    skills_to_display_lines,
    validate_resume_document_payload,
)


def _flat_gainwell_tesla_rws_experience_block():
    return [
        {
            "company": "",
            "title": "",
            "date_range": "",
            "location": "",
            "bullets": [
                "Gainwell Technologies | Senior Business Systems Analyst / Senior UAT Lead | April 2024 – Present | Remote",
                "Led UAT for Provider Portal.",
                "Tesla | Data Specialist (Autopilot) | July 2020 – June 2022 | San Mateo, CA",
                "Supported Autopilot data pipelines.",
                "RWS Moravia (Client: Apple) | Business Data Technician | June 2019 – June 2020 | Sunnyvale, CA",
                "Maintained localization data workflows.",
            ],
        }
    ]


def _resume_fixture_for_summary() -> dict:
    raw = """
    Gainwell Technologies Senior Business Systems Analyst UAT Lead
    user acceptance testing regulatory compliance enterprise systems
    validation workflows cross-functional regulated environments
    6+ years of experience
    """
    experience = [
        {
            "company": "Gainwell Technologies",
            "title": "Senior Business Systems Analyst / Senior UAT Lead",
            "date_range": "April 2024 – Present",
            "location": "Remote",
            "bullets": ["Led UAT for Provider Portal."],
        }
    ]
    return {
        "raw_text": raw,
        "sections": {"experience": experience, "projects": [], "education": [], "certifications": [], "skills": []},
    }


def main() -> int:
    print("Final cleanup / structure sanity check")
    print("=" * 60)
    errors: list[str] = []

    proj_raw = [
        {
            "name": "Personal Project - Analytics Dashboard",
            "bullets": [
                "Shipped a metrics dashboard.",
                "Education",
                "Certifications",
                "Education: MBA, Example University",
                "Data & Analytics: SQL, Python",
                "Certifications: CompTIA Security+",
            ],
        }
    ]
    proj_scrubbed, extra_skills, extra_edu, extra_cert = prepare_project_blocks_for_docx(proj_raw)
    cert_rows = [
        {"name": "Core Skills", "issuer": "", "date": "", "bullets": []},
        {"name": "CompTIA Security+", "issuer": "CompTIA", "date": "2020", "bullets": []},
        {
            "name": "IIBA Certification",
            "issuer": "IIBA",
            "date": "2018",
            "bullets": ["Testing & Governance: SLA Management"],
        },
    ]
    skills_in = merge_distinct_skill_lines(
        [
            "Data & Analytics: SQL, Power BI",
            "Systems & Platforms: Azure, Jira",
            "Documentation & Modeling: BRDs",
        ],
        extra_skills,
    )
    payload = build_resume_document_payload(
        name="Sanity User",
        contact="u@example.com",
        summary="placeholder",
        summary_source="sanity",
        experience_blocks=_flat_gainwell_tesla_rws_experience_block(),
        projects=proj_scrubbed,
        education=[{"degree": "B.S. CS", "institution": "State U", "date": "2014", "location": ""}],
        certifications=cert_rows,
        skills=skills_in,
    )
    validate_resume_document_payload(payload)
    ex = payload.experience

    # --- 1. Tesla company above Data Specialist (Autopilot) ---
    print("\n=== 1. Tesla as company above Data Specialist (Autopilot) ===")
    if len(ex) < 2:
        errors.append("need at least 2 experience entries for Tesla check")
        print("  FAIL: not enough experience rows")
    else:
        e1 = ex[1]
        h = experience_entry_header_lines(e1)
        print(f"  company field: {e1.company!r}")
        print(f"  role field: {e1.role!r}")
        print(f"  header_lines: {json.dumps(h, ensure_ascii=False)}")
        if (e1.company or "").strip().lower() != "tesla":
            errors.append("experience[1].company should be Tesla")
            print("  FAIL: company is not Tesla")
        elif h and h[0].strip().lower() != "tesla":
            errors.append("first header line should be Tesla")
            print("  FAIL: first rendered header is not Tesla")
        elif "autopilot" not in (e1.role or "").lower():
            errors.append("Autopilot missing from role")
            print("  FAIL: role missing Autopilot")
        else:
            print("  OK: Tesla is company; role contains Autopilot")

    # --- 2. RWS Moravia as separate third entry ---
    print("\n=== 2. RWS Moravia as separate third entry ===")
    if len(ex) < 3:
        errors.append("expected 3 distinct jobs (Gainwell, Tesla, RWS)")
        print(f"  FAIL: got {len(ex)} entries, need 3")
    else:
        e2 = ex[2]
        h = experience_entry_header_lines(e2)
        print(f"  entry[2] company: {e2.company!r}")
        print(f"  entry[2] role: {e2.role!r}")
        print(f"  header_lines: {json.dumps(h, ensure_ascii=False)}")
        if "rws" not in (e2.company or "").lower():
            errors.append("third entry company should include RWS Moravia")
            print("  FAIL: RWS not company on entry[2]")
        elif (ex[1].company or "").strip().lower() == (e2.company or "").strip().lower():
            errors.append("Tesla and RWS must not share the same company field")
            print("  FAIL: company collision between entry 2 and 3")
        else:
            print("  OK: third entry is RWS Moravia (distinct from Tesla)")

    # --- 3. Personal Project: only project bullets ---
    print("\n=== 3. Personal Project contains only project-related bullets ===")
    fp = payload.projects[0]
    print(f"  bullets: {json.dumps(list(fp.bullets), ensure_ascii=False)}")
    if len(fp.bullets) != 1 or "dashboard" not in fp.bullets[0].lower():
        errors.append("project should keep a single project bullet")
        print("  FAIL: unexpected project bullets")
    else:
        print("  OK: single project achievement bullet retained")

    # --- 4. No education / certifications under Personal Project ---
    print("\n=== 4. No education or certifications duplicated under Personal Project ===")
    joined = "\n".join(fp.bullets).lower()
    bad = False
    if "mba" in joined or "example university" in joined:
        bad = True
        errors.append("degree/MBA text leaked into project")
    if "comptia" in joined or "security+" in joined:
        bad = True
        errors.append("certification vendor text leaked into project")
    if "education:" in joined or "certifications:" in joined:
        bad = True
        errors.append("education:/certifications: line in project")
    if bad:
        print("  FAIL: edu/cert leakage in project")
    else:
        print("  OK: no edu/cert content under project")

    # --- 5. Certifications section: only certifications ---
    print("\n=== 5. Certifications payload: certification-shaped rows only ===")
    cert_entries = dict_rows_to_certification_entries(cert_rows)
    print(
        json.dumps(
            [{"name": c.name, "issuer": c.issuer, "bullets": c.bullets} for c in cert_entries],
            ensure_ascii=False,
            indent=2,
        )
    )
    for c in cert_entries:
        blob = f"{c.name} {c.issuer} {' '.join(c.bullets)}".lower()
        if "b.s." in blob or "computer science" in blob or "university" in blob and "degree" in blob:
            errors.append("degree-like content in certification entry")
            print(f"  FAIL: degree language in cert row: {c.name!r}")

    # --- 6. No skill bucket lines in Certifications ---
    print("\n=== 6. No skill bucket lines in Certifications ===")
    sk_bad = False
    for c in cert_entries:
        for line in [c.name, c.issuer, *c.bullets]:
            t = (line or "").strip()
            if t and skill_bucket_line_redirects_to_skills(t):
                sk_bad = True
                errors.append(f"skill bucket pattern in cert payload: {t[:80]!r}")
    if sk_bad:
        print("  FAIL: skill bucket text in certifications")
    else:
        print("  OK: no skill bucket lines in certification entries")

    # --- 7. Skills: grouped categories present ---
    print("\n=== 7. Skills section contains grouped skill categories ===")
    disp = skills_to_display_lines(list(payload.skills))
    print(f"  skills_payload: {json.dumps(payload.skills, ensure_ascii=False, indent=2)}")
    print(f"  display_lines: {json.dumps(disp, ensure_ascii=False, indent=2)}")
    need = ("data & analytics", "systems & platforms", "documentation & modeling")
    joined_sk = "\n".join(disp).lower()
    for label in need:
        if label not in joined_sk:
            errors.append(f"missing skills group: {label}")
            print(f"  FAIL: missing {label}")
    if all(label in joined_sk for label in need):
        print("  OK: all expected grouped categories present in skills display")

    # --- 8. Summary is not generic ---
    print("\n=== 8. Summary is not generic (grounded selector) ===")
    resume = _resume_fixture_for_summary()
    grounding = _build_grounding_corpus(
        resume, list(resume["sections"]["experience"]), []
    )
    summary, src = strongest_summary_from_resume("", "strong", resume, grounding)
    print(f"  summary_source: {src!r}")
    print(f"  summary: {summary!r}")
    weak_only = re.compile(
        r"(?i)^professional\s+with\s+experience\s+in\s+\w+,\s+\w+,\s+and\s+\w+\.\s*$"
    )
    if len(summary.strip()) < 40:
        errors.append("summary too short / empty")
        print("  FAIL: summary too short")
    elif weak_only.match(summary.strip()):
        errors.append("summary is generic Professional with experience in A, B, and C.")
        print("  FAIL: generic three-pillar Professional opener")
    elif src not in (
        "identity_structured",
        "identity_forward_dense",
        "tailored",
        "outcome_phrase",
        "resume_fallback",
    ):
        errors.append(f"unexpected summary source: {src}")
        print(f"  WARN: unusual source {src}")
    else:
        print("  OK: summary has substance and acceptable source")

    print("\n" + "=" * 60)
    if errors:
        print("RESULT: FAILED")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("RESULT: PASSED - clean structure, no leakage, clear identities.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

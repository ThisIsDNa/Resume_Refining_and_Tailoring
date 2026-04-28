"""
Targeted sanity checks: experience identity order, profile stripping, project/skills isolation.

These encode the export pipeline contracts for DOCX assembly (structure only).
"""

import inspect
import unittest

from app.services.resume_document_assembly import (
    ExperienceEntry,
    ResumeContractError,
    _count_distinct_date_spans_in_header_metadata,
    _finalize_experience_entries_sealed,
    _line_looks_like_role_header,
    _valid_job_identity,
    build_experience_entries_identity_first,
    build_resume_document_payload,
    coalesce_skills_for_export,
    dict_projects_to_entries,
    experience_blocks_to_entries,
    experience_blocks_to_provisional_entries,
    experience_entry_header_lines,
    merge_distinct_skill_lines,
    merge_pure_orphan_bullet_entries_into_adjacent_identity,
    prepare_project_blocks_for_docx,
    skills_to_display_lines,
    validate_resume_document_payload,
)


def _assert_no_bullet_entry_without_identity(payload) -> None:
    """Same contract as validate_resume_document_payload for experience bullets (test-only)."""
    for i, e in enumerate(payload.experience):
        if e.bullets and not ((e.company or "").strip() or (e.role or "").strip()):
            raise AssertionError(
                f"experience[{i}]: bullets require company or role (sanity check failed before validate)"
            )


def _first_experience_from_gainwell_block():
    block = {
        "company": "Gainwell Technologies",
        "title": "Senior Business Systems Analyst / Senior UAT Lead",
        "date_range": "April 2024 – Present",
        "location": "Remote",
        "bullets": [
            "Role Overview",
            "Achievements",
            "Senior Business Systems Analyst / UAT Lead with 6+ years of experience in healthcare.",
            "Recognized for translating ambiguous requirements into testable outcomes.",
            "Delivered UAT planning for the Provider Portal initiative.",
        ],
    }
    return experience_blocks_to_entries([block])[0]


class TestExportSanityExperienceIdentity(unittest.TestCase):
    def test_1_header_render_order_company_role_then_date_location(self):
        """Visible order: company, role, location and date on separate lines when both set."""
        ent = _first_experience_from_gainwell_block()
        lines = experience_entry_header_lines(ent)
        self.assertGreaterEqual(len(lines), 4, msg=lines)
        self.assertEqual(lines[0], "Gainwell Technologies")
        self.assertIn("Senior Business Systems Analyst", lines[1])
        self.assertIn("Remote", lines[2])
        self.assertIn("April", lines[3])
        # Bullets follow in payload; header lines must not duplicate as first bullet
        if ent.bullets:
            self.assertNotEqual(ent.bullets[0].strip(), lines[0])

    def test_2_gainwell_is_first_visible_header_line(self):
        ent = _first_experience_from_gainwell_block()
        hdr = experience_entry_header_lines(ent)
        self.assertTrue(hdr, "expected non-empty header lines")
        self.assertEqual(hdr[0], "Gainwell Technologies")

    def test_3_no_profile_summary_phrasing_in_experience_bullets(self):
        ent = _first_experience_from_gainwell_block()
        blob = " ".join(ent.bullets).lower()
        self.assertNotIn("with 6+ years", blob)
        self.assertNotIn("recognized for translating", blob)

    def test_4_role_overview_and_achievements_labels_not_in_bullets(self):
        ent = _first_experience_from_gainwell_block()
        joined = "\n".join(ent.bullets)
        self.assertNotIn("Role Overview", joined)
        self.assertNotRegex(joined, r"(?i)^\s*Achievements\s*$")
        # Standalone achievements heading removed; allow word inside real bullets if ever needed
        self.assertNotIn("Role Overview", joined)


class TestPreValidationExperienceIdentityContract(unittest.TestCase):
    """Runs the same identity rules the validator enforces; confirms assembly + validate OK."""

    def test_no_bullet_entry_without_company_or_role_before_validate(self):
        payload = build_resume_document_payload(
            name="N",
            contact="c",
            summary="S",
            summary_source="t",
            experience_blocks=[
                {
                    "company": "Gainwell Technologies",
                    "title": "Senior Business Systems Analyst / Senior UAT Lead",
                    "date_range": "April 2024 – Present",
                    "location": "Remote",
                    "bullets": ["Delivered outcome A."],
                }
            ],
            projects=[],
            education=[],
            certifications=[],
            skills=["Data & Analytics: SQL"],
        )
        _assert_no_bullet_entry_without_identity(payload)
        validate_resume_document_payload(payload)

    def test_first_entry_gainwell_identity_and_validate_passes(self):
        payload = build_resume_document_payload(
            name="N",
            contact="c",
            summary="S",
            summary_source="t",
            experience_blocks=[
                {
                    "company": "Gainwell Technologies",
                    "title": "Senior Business Systems Analyst / Senior UAT Lead",
                    "date_range": "April 2024 – Present",
                    "location": "Remote",
                    "bullets": ["Led UAT for Provider Portal."],
                }
            ],
            projects=[],
            education=[],
            certifications=[],
            skills=[],
        )
        fe = payload.experience[0]
        self.assertEqual((fe.company or "").strip(), "Gainwell Technologies")
        self.assertIn("Senior Business Systems Analyst", (fe.role or "").strip())
        self.assertIn("UAT Lead", (fe.role or "").strip())
        self.assertIn("April", (fe.date or "").strip())
        self.assertIn("Present", (fe.date or "").strip())
        self.assertIn("Remote", (fe.location or "").strip())
        _assert_no_bullet_entry_without_identity(payload)
        validate_resume_document_payload(payload)

    def test_validate_rejects_bullet_only_without_identity(self):
        bad = ExperienceEntry("", "", "April 2024", "Remote", ["Only bullets"])
        payload = build_resume_document_payload(
            name="N",
            contact="c",
            summary="S",
            summary_source="t",
            experience_blocks=[],
            projects=[],
            education=[],
            certifications=[],
            skills=[],
        )
        payload.experience = [bad]
        with self.assertRaises(ResumeContractError):
            validate_resume_document_payload(payload)


class TestSealedExperienceSegmentation(unittest.TestCase):
    def test_pure_orphan_bullets_merge_forward_into_adjacent_gainwell(self):
        """Pure bullet-only row + following valid job → one sealed entry (DOCX two-block pattern)."""
        merged = merge_pure_orphan_bullet_entries_into_adjacent_identity(
            [
                ExperienceEntry("", "", "", "", ["Resolved 50+ overdue SLA deliverables."]),
                ExperienceEntry(
                    "Gainwell Technologies",
                    "Senior Business Systems Analyst / Senior UAT Lead",
                    "April 2024 – Present",
                    "Remote",
                    ["Delivered UAT planning."],
                ),
            ]
        )
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].company, "Gainwell Technologies")
        self.assertIn("Senior Business Systems Analyst", merged[0].role)
        self.assertTrue(any("Resolved 50+" in b for b in merged[0].bullets))
        self.assertTrue(any("Delivered UAT" in b for b in merged[0].bullets))
        _finalize_experience_entries_sealed(merged)

    def test_trailing_pure_orphan_merges_backward_into_prior_job(self):
        merged = merge_pure_orphan_bullet_entries_into_adjacent_identity(
            [
                ExperienceEntry(
                    "Gainwell Technologies",
                    "Senior Business Systems Analyst / Senior UAT Lead",
                    "April 2024 – Present",
                    "Remote",
                    ["First bullet."],
                ),
                ExperienceEntry("", "", "", "", ["Trailing bucket only."]),
            ]
        )
        self.assertEqual(len(merged), 1)
        self.assertIn("Trailing bucket", "\n".join(merged[0].bullets))
        _finalize_experience_entries_sealed(merged)

    def test_metadata_orphan_with_date_location_merges_into_gainwell(self):
        """API often duplicates date/location on a bullet-only row — still identity-less; merges forward."""
        merged = merge_pure_orphan_bullet_entries_into_adjacent_identity(
            [
                ExperienceEntry(
                    "",
                    "",
                    "April 2024 – Present",
                    "Remote",
                    ["Orphan bullet with no company or role."],
                ),
                ExperienceEntry(
                    "Gainwell Technologies",
                    "Senior Business Systems Analyst / Senior UAT Lead",
                    "April 2024 – Present",
                    "Remote",
                    ["Delivered UAT planning."],
                ),
            ]
        )
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].company, "Gainwell Technologies")
        self.assertIn("Orphan bullet", "\n".join(merged[0].bullets))
        _finalize_experience_entries_sealed(merged)

    def test_identity_less_orphan_with_no_adjacent_identity_raises(self):
        """Cannot merge: identity-less bullets with no valid neighbor context."""
        with self.assertRaises(ResumeContractError):
            _finalize_experience_entries_sealed(
                merge_pure_orphan_bullet_entries_into_adjacent_identity(
                    [
                        ExperienceEntry("", "", "", "", ["Lonely bullet."]),
                    ]
                )
            )

    def test_multiple_date_ranges_in_one_entry_is_clamped_before_seal(self):
        """Merged date spans in one row are split: first span stays in header, rest → bullets."""
        out = _finalize_experience_entries_sealed(
            [
                ExperienceEntry(
                    "Gainwell Technologies",
                    "Analyst",
                    "April 2024 – Present · July 2020 – June 2022",
                    "Remote",
                    ["One bullet."],
                ),
            ]
        )
        self.assertTrue(out)
        for e in out:
            self.assertLessEqual(
                _count_distinct_date_spans_in_header_metadata(e.date, e.location),
                1,
                msg=(e.date, e.location, e.bullets),
            )

    def test_three_headers_in_one_flat_block_yield_three_entries(self):
        rows = experience_blocks_to_entries(
            [
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
        )
        self.assertEqual(len(rows), 3)
        self.assertIn("Gainwell", rows[0].company)
        self.assertIn("Senior Business Systems", rows[0].role)
        self.assertIn("2024", rows[0].date)
        self.assertIn("Remote", rows[0].location)
        self.assertIn("Tesla", rows[1].company)
        self.assertIn("Autopilot", rows[1].role)
        self.assertIn("San Mateo", rows[1].location)
        self.assertIn("RWS", rows[2].company)
        self.assertIn("Business Data", rows[2].role)
        self.assertIn("Sunnyvale", rows[2].location)

    def test_structured_gainwell_embedded_tesla_pipe_header_splits_into_new_entry(self) -> None:
        """Bullets must not retain a later job’s pipe header — it becomes a new experience row."""
        filler = ["Achievement line %s for UAT coverage." % i for i in range(14)]
        tesla = (
            "Tesla | Data Specialist (Autopilot) | July 2020 – June 2022 | San Mateo, CA"
        )
        rows = experience_blocks_to_entries(
            [
                {
                    "company": "Gainwell Technologies",
                    "title": "Senior Business Systems Analyst / Senior UAT Lead",
                    "date_range": "April 2024 – Present",
                    "location": "Remote",
                    "bullets": filler + [tesla, "Supported metrics refresh."],
                }
            ]
        )
        self.assertGreaterEqual(len(rows), 2)
        g = rows[0]
        self.assertIn("Gainwell", g.company)
        for b in g.bullets:
            self.assertFalse(
                _line_looks_like_role_header(b),
                msg=f"first entry bullets must not contain job-header-shaped lines: {b!r}",
            )
        self.assertTrue(any("Tesla" in (r.company or "") for r in rows[1:]))


class TestExportSanityProjectsAndSkills(unittest.TestCase):
    def test_5_personal_project_only_project_bullets_after_prepare(self):
        scrubbed, extra_skills, extra_edu, _extra_cert = prepare_project_blocks_for_docx(
            [
                {
                    "name": "Personal Project — Analytics Dashboard",
                    "subtitle": "Testing & Governance: should not stay as subtitle",
                    "bullets": [
                        "Built prototype using React and API integration.",
                        "Testing & Governance: SLA Management, QA Framework Design",
                        "Education: MBA, State University",
                    ],
                }
            ]
        )
        self.assertEqual(scrubbed[0]["bullets"], [scrubbed[0]["bullets"][0]])
        self.assertIn("Built prototype", scrubbed[0]["bullets"][0])
        self.assertTrue(any("Testing & Governance" in x for x in extra_skills))
        self.assertTrue(any("MBA" in (e.get("degree") or "") for e in extra_edu))
        entries = dict_projects_to_entries(scrubbed)
        self.assertEqual(len(entries), 1)
        self.assertIn("Dashboard", entries[0].name)
        for b in entries[0].bullets:
            self.assertNotRegex(b, r"(?i)education\s*:")
            self.assertNotRegex(b, r"(?i)testing\s*&\s*governance\s*:")

    def test_6_final_skills_includes_all_grouped_categories(self):
        sections = {
            "skills": [
                "Data & Analytics: SQL, Power BI",
                "Systems & Platforms: Azure, Jira",
            ]
        }
        raw = (
            "\n".join(
                [
                    "SKILLS",
                    "Testing & Governance: SLA Management, QA",
                    "Documentation & Modeling: BRD, process maps",
                ]
            )
            + "\n"
        )
        merged = coalesce_skills_for_export(sections, raw)
        joined = "\n".join(merged)
        self.assertIn("Data & Analytics", joined)
        self.assertIn("Systems & Platforms", joined)
        self.assertIn("Testing & Governance", joined)
        self.assertIn("Documentation & Modeling", joined)
        display = skills_to_display_lines(merged)
        self.assertGreaterEqual(len(display), 4)

    def test_6b_skills_global_scan_without_skills_header(self):
        raw = (
            "Experience\nSome job\n\n"
            "Systems & Platforms: Azure, Jira\n"
            "Data & Analytics: SQL, Power BI\n"
        )
        merged = coalesce_skills_for_export({"skills": []}, raw)
        joined = "\n".join(merged)
        self.assertIn("Systems & Platforms", joined)
        self.assertIn("Data & Analytics", joined)
        self.assertGreaterEqual(len(skills_to_display_lines(merged)), 2)

    def test_7_full_payload_first_experience_and_skills_clean(self):
        """End-to-end payload: first job identity + skills list; projects scrubbed."""
        exp_block = {
            "company": "Gainwell Technologies",
            "title": "Senior Business Systems Analyst",
            "date_range": "April 2024 – Present",
            "location": "Remote",
            "bullets": ["Role Overview", "Owned UAT cycles for claims module."],
        }
        proj_scrubbed, extra, _, _ = prepare_project_blocks_for_docx(
            [
                {
                    "name": "Portfolio App",
                    "bullets": ["Systems & Platforms: AWS, Docker", "Implemented CI pipeline."],
                }
            ]
        )
        skills_raw_text = "SKILLS\nDocumentation & Modeling: BRDs\n"
        skills = merge_distinct_skill_lines(
            coalesce_skills_for_export({"skills": ["Data & Analytics: SQL"]}, skills_raw_text),
            extra,
        )
        payload = build_resume_document_payload(
            name="Test User",
            contact="t@example.com",
            summary="Summary line.",
            summary_source="test",
            experience_blocks=[exp_block],
            projects=proj_scrubbed,
            education=[],
            certifications=[],
            skills=skills,
        )
        fe = payload.experience[0]
        self.assertEqual(experience_entry_header_lines(fe)[0], "Gainwell Technologies")
        self.assertTrue(all("Role Overview" not in b for b in fe.bullets))
        fp = payload.projects[0]
        self.assertEqual(len(fp.bullets), 1)
        self.assertIn("CI pipeline", fp.bullets[0])
        sk_blob = "\n".join(payload.skills)
        self.assertIn("Documentation & Modeling", sk_blob)
        self.assertIn("Systems & Platforms", sk_blob)
        _assert_no_bullet_entry_without_identity(payload)
        validate_resume_document_payload(payload)


class TestExperienceIdentityFirstSegmentation(unittest.TestCase):
    def test_block_date_location_not_prepended_as_bullets(self) -> None:
        """
        Identity-first construction: API date_range/location must not be injected as literal
        leading lines in the bullet list (they bind to the first header row's fields).
        """
        rows = experience_blocks_to_entries(
            [
                {
                    "company": "",
                    "title": "",
                    "date_range": "April 2024 – Present",
                    "location": "Remote",
                    "bullets": [
                        "Leading achievement before header line.",
                        "Gainwell Technologies | Senior Business Systems Analyst | April 2024 – Present | Remote",
                        "Second bullet after identity.",
                    ],
                }
            ]
        )
        self.assertEqual(len(rows), 1)
        fe = rows[0]
        self.assertIn("Gainwell", fe.company)
        self.assertTrue(fe.bullets, msg="expected bullets after merge")
        self.assertIn("Leading achievement", fe.bullets[0])
        self.assertNotEqual(fe.bullets[0].strip(), "April 2024 – Present")
        self.assertNotEqual(fe.bullets[0].strip(), "Remote")
        self.assertRegex((fe.date or "") + (fe.location or ""), r"(2024|Present|Remote)")


def _flat_gainwell_tesla_rws_experience_block() -> list[dict]:
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


class TestExperienceConstructionIdentityFirst(unittest.TestCase):
    """Construction sanity: identity-first rows, Gainwell → Tesla → RWS ordering."""

    def test_structured_tesla_block_splits_three_line_rws_fragment(self) -> None:
        """RWS as standalone employer lines + title + date must not remain under Tesla."""
        rows = experience_blocks_to_entries(
            [
                {
                    "company": "Tesla",
                    "title": "Data Specialist (Autopilot)",
                    "date_range": "July 2020 – June 2022",
                    "location": "San Mateo, CA",
                    "bullets": [
                        "Supported Autopilot data pipelines.",
                        "RWS Moravia (Client: Apple)",
                        "Business Data Technician",
                        "June 2019 – June 2020",
                        "Maintained localization data workflows.",
                    ],
                }
            ]
        )
        self.assertEqual(len(rows), 2, msg=[(e.company, e.role, e.bullets) for e in rows])
        self.assertEqual(rows[0].company.strip(), "Tesla")
        self.assertIn("RWS", rows[1].company)
        self.assertEqual(rows[1].role.strip(), "Business Data Technician")

    def test_structured_tesla_block_splits_rws_pipe_header_into_new_entry(self) -> None:
        """Later employer in bullets must start a new row, not stay under Tesla."""
        rows = experience_blocks_to_entries(
            [
                {
                    "company": "Tesla",
                    "title": "Data Specialist (Autopilot)",
                    "date_range": "July 2020 – June 2022",
                    "location": "San Mateo, CA",
                    "bullets": [
                        "Supported Autopilot data pipelines.",
                        "RWS Moravia (Client: Apple) | Business Data Technician | June 2019 – June 2020 | Sunnyvale, CA",
                        "Maintained localization data workflows.",
                    ],
                }
            ]
        )
        self.assertEqual(len(rows), 2, msg=[(e.company, e.role, e.bullets) for e in rows])
        self.assertEqual(rows[0].company.strip(), "Tesla")
        self.assertIn("RWS", rows[1].company)
        self.assertEqual(rows[1].role.strip(), "Business Data Technician")
        self.assertEqual(rows[0].bullets, ["Supported Autopilot data pipelines."])
        self.assertEqual(rows[1].bullets, ["Maintained localization data workflows."])

    def test_final_entries_identity_first_gainwell_tesla_rws(self) -> None:
        rows = experience_blocks_to_entries(_flat_gainwell_tesla_rws_experience_block())
        self.assertEqual(len(rows), 3)

        # 1: no ship-ready row lacks company or role when it has bullets.
        for i, ent in enumerate(rows):
            if ent.bullets:
                self.assertTrue(
                    (ent.company or "").strip() or (ent.role or "").strip(),
                    msg=f"entry[{i}] has bullets but no identity",
                )

        # 4–6: deterministic employer order.
        self.assertIn("Gainwell", rows[0].company)
        self.assertIn("Tesla", rows[1].company)
        self.assertIn("RWS", rows[2].company)

        # 2–3, 7: bullets are content only — no job-header lines or raw identity duplicates after identity.
        for i, ent in enumerate(rows):
            self.assertTrue(
                (ent.company or "").strip() or (ent.role or "").strip(),
                msg=f"entry[{i}]",
            )
            for j, b in enumerate(ent.bullets):
                self.assertFalse(
                    _line_looks_like_role_header(b),
                    msg=f"entry[{i}] bullet[{j}] looks like a job header (identity must not follow bullets): {b!r}",
                )
                bl = b.lower().strip()
                if (ent.company or "").strip():
                    self.assertNotEqual(
                        bl,
                        (ent.company or "").strip().lower(),
                        msg=f"entry[{i}] bullet duplicates company line",
                    )
                if (ent.role or "").strip():
                    self.assertNotEqual(
                        bl,
                        (ent.role or "").strip().lower(),
                        msg=f"entry[{i}] bullet duplicates role line",
                    )
            if ent.bullets:
                self.assertFalse(
                    _line_looks_like_role_header(ent.bullets[0]),
                    msg=f"entry[{i}] must not begin bullets with a header-shaped line",
                )

    def test_provisional_segmentation_only_creates_rows_with_identity_headers(self) -> None:
        """Every segmented row has valid identity before bullets are attached (construction model)."""
        prov = experience_blocks_to_provisional_entries(_flat_gainwell_tesla_rws_experience_block())
        for i, ent in enumerate(prov):
            self.assertTrue(
                _valid_job_identity(ent.company, ent.role),
                msg=f"provisional[{i}] missing company/role: {ent.company!r} {ent.role!r}",
            )


class TestPipelineWiringIdentityFirstExperienceBuilder(unittest.TestCase):
    """Pipeline wiring: DOCX payload must assemble experience only via identity-first builder."""

    def test_build_resume_document_payload_calls_identity_first_only(self) -> None:
        """Checks 1–3: single assembler name in bytecode; not legacy ``experience_blocks_to_entries``."""
        co = build_resume_document_payload.__code__
        self.assertIn(
            "build_experience_entries_identity_first",
            co.co_names,
            msg=f"expected builder in bytecode names, got: {co.co_names!r}",
        )
        self.assertNotIn(
            "experience_blocks_to_entries",
            co.co_names,
            msg="build_resume_document_payload must not reference experience_blocks_to_entries "
            f"(legacy path); names={co.co_names!r}",
        )
        src = inspect.getsource(build_resume_document_payload)
        self.assertRegex(
            src,
            r"build_experience_entries_identity_first\(\s*experience_blocks_identity_input\s*\)",
            msg="experience must be segmented from skill-stripped blocks, not raw experience_blocks",
        )
        self.assertNotRegex(
            src,
            r"(?<!def\s)experience_blocks_to_entries\s*\(\s*experience_blocks\s*\)",
            msg="direct call to experience_blocks_to_entries(experience_blocks) must not exist",
        )

    def test_identity_first_builder_matches_public_alias(self) -> None:
        blocks = _flat_gainwell_tesla_rws_experience_block()
        snap = lambda rows: [  # noqa: E731
            ((e.company or "").strip(), (e.role or "").strip(), (e.date or "").strip(), tuple(e.bullets))
            for e in rows
        ]
        self.assertEqual(
            snap(build_experience_entries_identity_first(blocks)),
            snap(experience_blocks_to_entries(blocks)),
        )

    def test_payload_first_entry_gainwell_identity_before_bullets(self) -> None:
        """Check 4: structured payload before DOCX — Gainwell identity fields, bullets are content."""
        payload = build_resume_document_payload(
            name="Test User",
            contact="t@example.com",
            summary="Business analyst with documented delivery and stakeholder experience.",
            summary_source="pipeline_wiring",
            experience_blocks=_flat_gainwell_tesla_rws_experience_block(),
            projects=[],
            education=[],
            certifications=[],
            skills=["SQL"],
        )
        self.assertGreaterEqual(len(payload.experience), 1)
        fe = payload.experience[0]
        self.assertEqual((fe.company or "").strip(), "Gainwell Technologies")
        self.assertIn("Senior Business Systems Analyst", (fe.role or ""))
        self.assertIn("UAT Lead", (fe.role or ""))
        self.assertTrue(fe.bullets, msg="expected bullets after identity on entry[0]")
        self.assertFalse(
            _line_looks_like_role_header(fe.bullets[0]),
            msg=f"first bullet must not be a job header line: {fe.bullets[0]!r}",
        )


if __name__ == "__main__":
    unittest.main()

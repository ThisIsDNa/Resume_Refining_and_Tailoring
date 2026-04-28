"""
Lifecycle sanity: provisional → normalized → orphan repair → final pre-validation.

Run: python -m unittest tests.test_experience_segmentation_lifecycle_sanity -v
"""

from __future__ import annotations

import sys
import unittest

from app.services.resume_document_assembly import (
    ExperienceEntry,
    HeaderCanonical,
    ResumeDocumentPayload,
    _finalize_experience_entries_sealed,
    _is_identity_less_bullet_entry,
    experience_blocks_to_entries,
    experience_segmentation_lifecycle_snapshots,
    experience_segmentation_lifecycle_snapshots_from_entries,
    validate_resume_document_payload,
)

# Same shape as bullet-only block + structured Gainwell + Tesla (orphan merges forward).
PROVISIONAL_ORPHAN_GAINWELL_TESLA = [
    ExperienceEntry(
        "",
        "",
        "April 2024 – Present",
        "Remote",
        [
            "Resolved 50+ overdue SLA deliverables across cross-functional teams.",
            "Frequently placed into ambiguous, undocumented environments requiring rapid discovery.",
            "Lead end-to-end functional validation aligning business rules with technical delivery.",
        ],
    ),
    ExperienceEntry(
        "Gainwell Technologies",
        "Senior Business Systems Analyst / Senior UAT Lead",
        "April 2024 – Present",
        "Remote",
        [],
    ),
    ExperienceEntry(
        "Tesla",
        "Data Specialist (Autopilot)",
        "July 2020 – June 2022",
        "San Mateo, CA",
        ["Tesla-only bullet for isolation check."],
    ),
]


def _print_lifecycle_stage(stage: str, entries: list[ExperienceEntry]) -> None:
    print(f"\n{'=' * 72}\n{stage}\n{'=' * 72}", file=sys.stderr)
    for idx in range(min(3, len(entries))):
        e = entries[idx]
        has_co = bool((e.company or "").strip())
        has_ro = bool((e.role or "").strip())
        has_bu = bool(e.bullets)
        print(
            f"  [{idx}] has_company={has_co} has_role={has_ro} has_bullets={has_bu} "
            f"company={e.company!r} role={e.role!r} date={e.date!r} location={e.location!r} "
            f"bullet_count={len(e.bullets)}",
            file=sys.stderr,
        )
        for j in range(min(2, len(e.bullets))):
            print(f"        bullet[{j}] {e.bullets[j][:90]!r}...", file=sys.stderr)


class TestExperienceSegmentationLifecycleSanity(unittest.TestCase):
    def test_lifecycle_orphan_merges_gainwell_first_no_bullet_only_survivors(self) -> None:
        snaps = experience_segmentation_lifecycle_snapshots_from_entries(
            [ExperienceEntry(x.company, x.role, x.date, x.location, list(x.bullets)) for x in PROVISIONAL_ORPHAN_GAINWELL_TESLA]
        )
        self.assertEqual(
            [s[0] for s in snaps],
            ["SEGMENT_PROVISIONAL", "NORMALIZED", "ORPHAN_REPAIR", "FINAL_PRE_VALIDATION"],
        )

        for stage, entries in snaps:
            _print_lifecycle_stage(stage, entries)
            for idx in range(min(3, len(entries))):
                e = entries[idx]
                has_co = bool((e.company or "").strip())
                has_ro = bool((e.role or "").strip())
                has_bu = bool(e.bullets)
                if stage in ("ORPHAN_REPAIR", "FINAL_PRE_VALIDATION"):
                    if has_bu:
                        self.assertTrue(
                            has_co or has_ro,
                            f"{stage}[{idx}]: no bullet-only rows after repair",
                        )
                if stage == "SEGMENT_PROVISIONAL" and idx == 0:
                    self.assertTrue(
                        has_bu and (not has_co) and (not has_ro),
                        "entry[0] must be bullet-only provisional (Gainwell bullets before identity row)",
                    )

        final_pre = snaps[-1][1]
        self.assertEqual(len(final_pre), 2, "orphan row removed; Gainwell + Tesla remain")
        self.assertFalse(any(_is_identity_less_bullet_entry(e) for e in final_pre))
        self.assertIn("Gainwell", final_pre[0].company)
        self.assertIn("Resolved 50+", "\n".join(final_pre[0].bullets))
        self.assertNotIn("Resolved 50+", "\n".join(final_pre[1].bullets))

        sealed = _finalize_experience_entries_sealed(final_pre)
        self.assertEqual(sealed[0].company, "Gainwell Technologies")
        validate_resume_document_payload(
            ResumeDocumentPayload(
                header=HeaderCanonical(name="N", contact="c"),
                summary="S",
                summary_source="t",
                experience=sealed,
                projects=[],
                education=[],
                certifications=[],
                skills=["SQL"],
            )
        )

    def test_lifecycle_from_structured_blocks_no_orphan(self) -> None:
        blocks = [
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
        ]
        snaps = experience_segmentation_lifecycle_snapshots(blocks)
        for stage, entries in snaps:
            _print_lifecycle_stage(stage, entries)
            for idx in range(min(3, len(entries))):
                e = entries[idx]
                if e.bullets:
                    self.assertTrue(
                        (e.company or "").strip() or (e.role or "").strip(),
                        f"{stage}[{idx}]",
                    )
        full = experience_blocks_to_entries(blocks)
        self.assertEqual(full[0].company, "Gainwell Technologies")
        validate_resume_document_payload(
            ResumeDocumentPayload(
                header=HeaderCanonical(name="N", contact="c"),
                summary="S",
                summary_source="t",
                experience=full,
                projects=[],
                education=[],
                certifications=[],
                skills=[],
            )
        )

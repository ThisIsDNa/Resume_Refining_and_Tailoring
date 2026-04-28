"""
Sanity: strong standalone role/title lines inside experience bullets must open a new job row.

Run from the backend directory:
  python scripts/run_standalone_role_boundary_sanity.py
"""

from __future__ import annotations

import sys
import unicodedata
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.resume_document_assembly import (  # noqa: E402
    _line_is_embedded_identity_fragment,
    _line_is_standalone_role_title,
    build_resume_document_payload,
    experience_blocks_to_entries,
    streaming_segmentation_trace,
    validate_resume_document_payload,
)

ROLE_LINE = "Data Specialist (Autopilot)"

# Structured Gainwell block with a trailing distinct role line (Tesla title) + Tesla achievement.
GAINWELL_WITH_EMBEDDED_ROLE_BLOCK = {
    "company": "Gainwell Technologies",
    "title": "Senior Business Systems Analyst / Senior UAT Lead",
    "date_range": "April 2024 – Present",
    "location": "Remote",
    "bullets": [
        "Led client demonstrations for all release phases, refining outputs through iterative feedback until formal acceptance.",
        "Developed a Selenium and Python automation tool to scrape client-facing webpages.",
        "Leveraged SQL to extract and validate CRM datasets, generate GIA reporting outputs, and simulate SLA boundary conditions by backdating case records for expedited workflow testing.",
        "Mapped cross-department data dependencies and integration points to strengthen end-to-end validation accuracy across interconnected systems.",
        ROLE_LINE,
        "Supported Autopilot data validation within a sensor-driven, production-scale environment.",
    ],
}


def _nfkc(s: str) -> str:
    return unicodedata.normalize("NFKC", (s or "").strip())


def _print_trace_focus(trace: list[dict], *, focus_substr: str) -> None:
    print("=== SEGMENTATION TRACE (focus: lines containing %r or role-boundary actions) ===\n" % focus_substr)
    for n, ev in enumerate(trace):
        rl = str(ev.get("raw_line") or "")
        act = str(ev.get("action") or "")
        det = str(ev.get("detected") or "")
        if focus_substr.lower() in rl.lower() or "standalone_role" in act or det == "role_boundary":
            preview = rl if len(rl) <= 100 else rl[:97] + "..."
            print(
                f"  #{n:>3}  phase={ev.get('phase')!s:<10}  ix={int(ev.get('line_index', -1)):>3}  "
                f"detected={det:<18}  action={act:<38}  raw_line={preview!r}"
            )
    print("\n=== FULL TRACE (all events) ===\n")
    print(f"{'#':>3}  {'phase':^10}  {'ix':>3}  {'detected':^18}  {'action':^36}  raw_line")
    print("-" * 130)
    for n, ev in enumerate(trace):
        rl = str(ev.get("raw_line") or "")
        preview = rl.replace("\n", " ")
        if len(preview) > 75:
            preview = preview[:72] + "..."
        print(
            f"{n:>3}  {str(ev.get('phase')):^10}  {int(ev.get('line_index', -1)):>3}  "
            f"{str(ev.get('detected')):^18}  {str(ev.get('action')):^36}  {preview!r}"
        )
    print()


def main() -> int:
    block = GAINWELL_WITH_EMBEDDED_ROLE_BLOCK
    synth_parts = [
        str(p).strip()
        for p in (block["company"], block["title"], block["date_range"], block["location"])
        if str(p).strip()
    ]
    leading = " | ".join(synth_parts)
    raw_bullets = [str(b).strip() for b in (block.get("bullets") or []) if str(b).strip()]
    stream = [leading] + raw_bullets

    trace, raw_entries = streaming_segmentation_trace(
        stream,
        block_date="",
        block_location="",
    )

    _print_trace_focus(trace, focus_substr=ROLE_LINE)

    # --- Check 2: Data Specialist line is never append_bullet in scan ---
    role_norm = _nfkc(ROLE_LINE).lower()
    bad = [
        ev
        for ev in trace
        if ev.get("phase") == "scan"
        and ev.get("action") == "append_bullet"
        and _nfkc(str(ev.get("raw_line") or "")).lower() == role_norm
    ]
    print("=== CHECK 2: role/title line must not be append_bullet in scan ===")
    if bad:
        print("FAIL:", bad)
        return 1
    if not _line_is_standalone_role_title(ROLE_LINE):
        print("FAIL: ROLE_LINE should classify as standalone role/title for this fixture")
        return 1
    print("OK: %r is standalone role/title and was not appended as a bullet in scan.\n" % ROLE_LINE)

    # --- Check 3 & 4: close_entry_standalone_role then start_new_entry with that role ---
    st = [ev for ev in trace if ev.get("phase") == "scan"]
    print("=== CHECK 3 & 4: close current entry, then new entry from standalone role ===")
    idx_close = next((i for i, ev in enumerate(st) if ev.get("action") == "close_entry_standalone_role"), None)
    idx_start = next((i for i, ev in enumerate(st) if ev.get("action") == "start_new_entry_standalone_role"), None)
    if idx_close is None or idx_start is None:
        print("FAIL: expected close_entry_standalone_role and start_new_entry_standalone_role in scan trace")
        return 1
    if idx_start != idx_close + 1:
        print("FAIL: expected start immediately after close, got close=%s start=%s" % (idx_close, idx_start))
        return 1
    start_ev = st[idx_start]
    if role_norm not in str(start_ev.get("raw_line") or "").lower():
        print("FAIL: start_new_entry should reference the role line, got %r" % (start_ev.get("raw_line"),))
        return 1
    print("OK: Gainwell closed, new row starts from standalone role line.\n")

    # Raw segmenter rows (pre-polish): second row should be Tesla-side role
    print("=== RAW SEGMENTER ROWS (pre-finalize) ===\n")
    for i, ent in enumerate(raw_entries):
        print(f"  [{i}] company={ent.company!r} role={ent.role!r} bullets={len(ent.bullets)}")
    tesla_like = [e for e in raw_entries if role_norm in (e.role or "").lower()]
    if not tesla_like:
        print("FAIL: no raw entry with Data Specialist role")
        return 1
    print()

    # --- Check 5: final experience rows ---
    final_rows = experience_blocks_to_entries([block])
    print("=== CHECK 5: no strong role/title header lines in final bullets ===")
    for ei, e in enumerate(final_rows):
        for j, b in enumerate(e.bullets):
            bt = str(b).strip()
            if _line_is_embedded_identity_fragment(bt):
                print(f"FAIL: experience[{ei}].bullets[{j}] fragment={bt!r}")
                return 1
            if _line_is_standalone_role_title(bt):
                print(f"FAIL: experience[{ei}].bullets[{j}] standalone role/title={bt!r}")
                return 1
    gainwell = next(r for r in final_rows if "gainwell" in (r.company or "").lower())
    tesla = next(r for r in final_rows if role_norm in (r.role or "").lower())
    if role_norm in " ".join(gainwell.bullets).lower():
        print("FAIL: role line leaked into Gainwell bullets text")
        return 1
    if not any("autopilot" in (b or "").lower() for b in tesla.bullets):
        print("FAIL: Tesla row should own the Autopilot achievement bullet")
        return 1
    print("OK: no role-like fragments in bullets; Gainwell vs Tesla split.\n")

    print("=== CHECK 6: validate_resume_document_payload (unchanged rules) ===")
    payload = build_resume_document_payload(
        name="Standalone role boundary sanity",
        contact="sanity@example.com",
        summary="Summary for contract check.",
        summary_source="sanity_script",
        experience_blocks=[block],
        projects=[],
        education=[],
        certifications=[],
        skills=["Data & Analytics: SQL"],
    )
    validate_resume_document_payload(payload)
    print("OK: validation passed.\n")

    print("All standalone role/title boundary sanity checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

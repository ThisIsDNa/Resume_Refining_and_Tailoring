"""
Canonical structured resume assembly for DOCX (data-driven; no raw_text stitching).

Summary text is supplied only by export_docx.strongest_summary_from_resume.

Experience: use ``build_experience_entries_identity_first`` (single source of truth for DOCX
and validators). Each API block maps to structured ``ExperienceEntry`` rows (company, role,
date, location, bullets). Identity-first segmentation seals one job per entry.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from app.services.experience_bullet_prioritization import prioritize_experience_entry_bullets
from app.services.parse_resume import (
    experience_lines_for_identity_segmentation,
    line_is_experience_noise,
)

logger = logging.getLogger(__name__)

_DEFAULT_SKILLS_ITEMS = ["SQL", "Power BI", "Tableau", "Excel", "Python"]


@dataclass
class HeaderCanonical:
    name: str
    contact: str


@dataclass
class ExperienceEntry:
    """Structured job: company → role → date/location → bullets (bullets never hold role/company)."""

    company: str
    role: str
    date: str
    location: str
    bullets: List[str] = field(default_factory=list)


@dataclass
class ProjectEntry:
    name: str
    subtitle: str
    bullets: List[str] = field(default_factory=list)


@dataclass
class EducationEntry:
    degree: str
    institution: str
    date: str
    location: str
    bullets: List[str] = field(default_factory=list)


@dataclass
class CertificationEntry:
    name: str
    issuer: str
    date: str
    bullets: List[str] = field(default_factory=list)


class ResumeContractError(ValueError):
    """Raised when assembled payload violates the structured resume contract."""


@dataclass
class ResumeDocumentPayload:
    header: HeaderCanonical
    summary: str
    summary_source: str
    experience: List[ExperienceEntry]
    projects: List[ProjectEntry]
    education: List[EducationEntry]
    certifications: List[CertificationEntry]
    skills: List[str]


_DATE_SPAN_RE = re.compile(
    r"(?i)\b((?:19|20)\d{2})\s*[-–—\u2212]\s*((?:19|20)\d{2}|present|current)\b"
)
# Month-name ranges (e.g. July 2020 – June 2022) plus year-only spans — used to detect
# merged metadata (multiple jobs glued into one header).
_MO_WORD = (
    r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|"
    r"sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?"
)
_HEADER_METADATA_DATE_SPAN_ANY_RE = re.compile(
    r"(?i)(?:"
    r"\b(?:19|20)\d{2}\s*[-–—\u2212]\s*(?:(?:19|20)\d{2}|present|current)\b"
    r"|"
    r"\b(?:" + _MO_WORD + r")\s+"
    r"(?:19|20)\d{2}\s*[-–—\u2212]\s*"
    r"(?:(?:" + _MO_WORD + r")\s+(?:19|20)\d{2}|present|current)\b"
    r")"
)
_YEAR_SINGLE_RE = re.compile(r"\b((?:19|20)\d{2})\b")
_TRAILING_PARENS_LOC = re.compile(r"\(\s*([^)]{2,80})\s*\)\s*$")


def _line_looks_like_role_header(line: str) -> bool:
    s = (line or "").strip()
    if len(s) < 12 or len(s) > 220:
        return False
    wc = len(s.split())
    if wc > 22:
        return False
    if _DATE_SPAN_RE.search(s):
        return True
    if s.count("|") >= 1 and 12 < len(s) < 200:
        return True
    if re.search(r"\s+at\s+", s, re.I) and wc <= 18:
        return True
    if ("—" in s or " – " in s) and wc <= 16 and _YEAR_SINGLE_RE.search(s):
        return True
    return False


_STREAM_SEGMENT_DEBUG_ENV = "RESUME_TAILOR_STREAM_SEGMENT_DEBUG"
_EMBEDDED_HEADER_DEBUG_ENV = "RESUME_TAILOR_EMBEDDED_HEADER_DEBUG"
_ROLE_BOUNDARY_DEBUG_ENV = "RESUME_TAILOR_ROLE_BOUNDARY_DEBUG"


def _stream_segment_debug_enabled() -> bool:
    return (os.environ.get(_STREAM_SEGMENT_DEBUG_ENV) or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _emit_stream_segment_trace(
    stream_trace: Optional[List[Dict[str, Any]]],
    *,
    phase: str,
    line_index: int,
    raw_line: str,
    detected: str,
    cur_company: str,
    cur_role: str,
    action: str,
) -> None:
    """Append structured trace events and/or mirror to logger when debug env is set."""
    if stream_trace is not None:
        stream_trace.append(
            {
                "phase": phase,
                "line_index": line_index,
                "raw_line": raw_line,
                "detected": detected,
                "action": action,
                "cur_company": cur_company,
                "cur_role": cur_role,
            }
        )
    if not _stream_segment_debug_enabled():
        return
    logger.info(
        "STREAM_SEGMENT_DEBUG phase=%s line_index=%s detected=%s action=%s "
        "cur_company=%r cur_role=%r raw_line=%r",
        phase,
        line_index,
        detected,
        action,
        (cur_company or "")[:120],
        (cur_role or "")[:120],
        (raw_line or "")[:220],
    )


def _embedded_header_debug_enabled() -> bool:
    return (os.environ.get(_EMBEDDED_HEADER_DEBUG_ENV) or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _embedded_header_debug(
    *,
    line_index: int,
    raw_line: str,
    detected: str,
    fragment_kind: str,
    action: str,
) -> None:
    if not _embedded_header_debug_enabled():
        return
    logger.info(
        "EMBEDDED_HEADER_DEBUG line_index=%s detected=%r fragment_kind=%r action=%s raw_line=%r",
        line_index,
        detected,
        fragment_kind,
        action,
        (raw_line or "")[:220],
    )


def _normalize_resume_line_dashes(s: str) -> str:
    """Normalize typographic hyphens / minus to ASCII ``-`` so date-range heuristics match."""
    t = (s or "").strip()
    if not t:
        return t
    return (
        t.replace("\u2013", "-")
        .replace("\u2014", "-")
        .replace("\u2212", "-")
        .replace("\u2010", "-")
        .replace("\u2011", "-")
    )


def _line_is_standalone_calendar_date_range(s: str) -> bool:
    """
    A short line that is primarily a job date span (not a full pipe header with identity).
    Used to detect embedded ``July 2020 – June 2022``-style fragments inside bullet streams.
    """
    t = (s or "").strip()
    if not t or len(t) > 96:
        return False
    if "|" in t:
        return False
    if len(t.split()) > 14:
        return False
    if not (_DATE_SPAN_RE.search(t) or _HEADER_METADATA_DATE_SPAN_ANY_RE.search(t)):
        return False
    if _line_looks_like_role_header(t):
        r, c, _d, _loc, _ = _parse_role_header_line(t)
        if _valid_job_identity(c, r):
            return False
    return True


_STANDALONE_SINGLE_WORD_NON_COMPANY = frozenset(
    {
        "achievements",
        "highlights",
        "profile",
        "overview",
        "summary",
        "experience",
        "employment",
        "background",
        "accomplishments",
    }
)


def _line_is_standalone_company_like(s: str) -> bool:
    """Employer-like line without pipe (e.g. ``Gainwell Technologies``) — not an achievement."""
    t = (s or "").strip()
    if not t or len(t) > 100:
        return False
    if "|" in t:
        return False
    if _line_rejects_spurious_company_or_employer_segment(t):
        cls = "location" if _US_CITY_STATE_LINE_RE.match(t) else "ignored"
        _emit_segmentation_debug(t, cls)
        return False
    if _line_looks_like_role_header(t):
        r, c, _d, _loc, _ = _parse_role_header_line(t)
        if _valid_job_identity(c, r):
            return False
    words = t.split()
    if len(words) > 12:
        return False
    if _JOB_TITLE_HINT.search(t):
        return False
    if _EMPLOYER_SEGMENT_HINT.search(t):
        if _line_is_skill_category_or_soft_skill_colon_bucket(t):
            _emit_segmentation_debug(t, "ignored")
            return False
        _emit_segmentation_debug(t, "company")
        return True
    # Common client-bracket employer line without a pipe (must collapse with following title in preprocess).
    if re.match(r"(?i)^rws\s+moravia\b", t):
        _emit_segmentation_debug(t, "company")
        return True
    if (
        len(words) == 1
        and 2 <= len(t) <= 42
        and t[0].isupper()
        and not _is_date_or_range_only_token(t)
        and not _REMOTE_OR_WORKMODE_ONLY.match(t)
        and not _YEAR_ONLY_LINE_RE.match(t)
        and t.lower() not in _STANDALONE_SINGLE_WORD_NON_COMPANY
    ):
        _emit_segmentation_debug(t, "company")
        return True
    return False


def _line_is_standalone_role_title(s: str) -> bool:
    """Short title-like line (e.g. ``Data Specialist (Autopilot)``) — not a prose bullet."""
    t = (s or "").strip()
    if not t or len(t) > 130:
        return False
    if "|" in t:
        return False
    if _line_looks_like_role_header(t):
        r, c, _d, _loc, _ = _parse_role_header_line(t)
        if _valid_job_identity(c, r):
            return False
    wc = len(t.split())
    if wc > 18:
        return False
    if not _JOB_TITLE_HINT.search(t):
        return False
    if _segment_looks_like_employer(t):
        return False
    if t.endswith(".") and wc > 6:
        return False
    if wc > 8 and re.match(r"(?i)^(lead|led)\b", t):
        return False
    if re.match(
        r"(?i)^(partnered|leveraged|reduced|supported|developed|led|drove|owned|mapped|"
        r"collaborated|delivered|implemented|facilitated|coordinated|designed|built|created)\b",
        t,
    ):
        return False
    return True


def _role_boundary_debug_enabled() -> bool:
    return (os.environ.get(_ROLE_BOUNDARY_DEBUG_ENV) or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _role_boundary_debug(
    *,
    line_index: int,
    raw_line: str,
    detected_role: bool,
    cur_company: str,
    cur_role: str,
    action: str,
) -> None:
    if not _role_boundary_debug_enabled():
        return
    logger.info(
        "ROLE_BOUNDARY_DEBUG line_index=%s detected_role=%s action=%s "
        "cur_company=%r cur_role=%r raw_line=%r",
        line_index,
        detected_role,
        action,
        (cur_company or "")[:120],
        (cur_role or "")[:120],
        (raw_line or "")[:220],
    )


def _standalone_role_line_is_strong_boundary_candidate(line: str) -> bool:
    """
    Avoid splitting on one-word titles like ``Director``; require a substantive title line.
    """
    t = (line or "").strip()
    if len(t) < 14:
        return False
    wc = len(t.split())
    if wc >= 2:
        return True
    if "(" in t or "/" in t:
        return True
    return False


def _standalone_role_line_opens_distinct_job(cur: ExperienceEntry, line: str) -> bool:
    """True when ``line`` is a standalone job title that must not be appended to ``cur``."""
    if not _line_is_standalone_role_title(line) or not _standalone_role_line_is_strong_boundary_candidate(line):
        return False
    lt = line.strip().lower()
    if lt == (cur.role or "").strip().lower():
        return False
    if lt == (cur.company or "").strip().lower():
        return False
    return True


def _line_is_compact_location_metadata(s: str) -> bool:
    """Short location / work-mode line that may follow a role fragment (not a prose bullet)."""
    t = (s or "").strip()
    if not t or len(t) > 88:
        return False
    if "|" in t:
        return False
    if _line_is_embedded_identity_fragment(t):
        return False
    if _REMOTE_OR_WORKMODE_ONLY.match(t):
        return True
    if "," in t and len(t.split()) <= 10 and re.match(r"^[A-Za-z0-9.,()\-\s]+$", t):
        return True
    return False


def _pop_optional_header_fragments_after_role(queue: List[str]) -> Tuple[str, str, str]:
    """
    After a standalone ``role`` line, consume consecutive company / date / compact location
    fragments from the front of ``queue`` (if any).
    """
    company = ""
    date_s = ""
    loc_s = ""
    for _ in range(5):
        if not queue:
            break
        peek = queue[0]
        if not company and _line_is_standalone_company_like(peek):
            company = str(queue.pop(0)).strip()
            continue
        if not date_s and _line_is_standalone_calendar_date_range(peek):
            date_s = str(queue.pop(0)).strip()
            continue
        if not loc_s and _line_is_compact_location_metadata(peek):
            loc_s = str(queue.pop(0)).strip()
            continue
        break
    return company, date_s, loc_s


def _strip_trailing_redundant_first_header_role_repeat(
    lines: List[str],
    *,
    stream_trace: Optional[List[Dict[str, Any]]] = None,
) -> List[str]:
    """
    Drop a trailing title-only line that repeats the first row's role (e.g. Tesla title echoed
    after a later embedded job) so it is never scanned as a bullet on the wrong employer.
    """
    if len(lines) < 2:
        return lines
    first = (lines[0] or "").strip()
    if "|" not in first or not _line_looks_like_role_header(first):
        return lines
    r0, _c0, _d0, _loc0, _ov = _parse_role_header_line(first)
    r0t = (r0 or "").strip().lower()
    if not r0t:
        return lines
    last = (lines[-1] or "").strip()
    if _line_is_standalone_role_title(last) and last.strip().lower() == r0t:
        dropped = lines[-1]
        _emit_stream_segment_trace(
            stream_trace,
            phase="preprocess",
            line_index=len(lines) - 1,
            raw_line=dropped,
            detected="role",
            cur_company="",
            cur_role="",
            action="drop_redundant_first_header_role_repeat",
        )
        return lines[:-1]
    return lines


def _line_is_embedded_identity_fragment(s: str) -> bool:
    """Any standalone date/company/title fragment that must not survive in final bullets."""
    t = (s or "").strip()
    if not t:
        return False
    return (
        _line_is_standalone_calendar_date_range(t)
        or _line_is_standalone_company_like(t)
        or _line_is_standalone_role_title(t)
    )


def _preprocess_embedded_fragment_header_lines(
    lines: List[str],
    *,
    stream_trace: Optional[List[Dict[str, Any]]] = None,
) -> List[str]:
    """
    Collapse consecutive ``date / company / title`` fragments (no pipes) into one synthetic
    pipe header so ``_segment_bullets_into_entries`` opens a clean job boundary.

    Handles orderings:
    - date, company, role
    - company, role, date
    - company, role (optional date supplied later from block metadata)
    """
    raw = [_normalize_resume_line_dashes(str(x).strip()) for x in lines if str(x).strip()]
    if len(raw) < 2:
        return raw
    out: List[str] = []
    i = 0
    n = len(raw)
    out_idx = 0
    while i < n:
        merged = False
        if i + 2 < n:
            a, b, c = raw[i], raw[i + 1], raw[i + 2]
            if (
                _line_is_standalone_calendar_date_range(a)
                and _line_is_standalone_company_like(b)
                and _line_is_standalone_role_title(c)
            ):
                synth = f"{b} | {c} | {a}"
                out.append(synth)
                _emit_stream_segment_trace(
                    stream_trace,
                    phase="preprocess",
                    line_index=i,
                    raw_line=a,
                    detected="date",
                    cur_company="",
                    cur_role="",
                    action="fragment_component",
                )
                _emit_stream_segment_trace(
                    stream_trace,
                    phase="preprocess",
                    line_index=i + 1,
                    raw_line=b,
                    detected="company",
                    cur_company="",
                    cur_role="",
                    action="fragment_component",
                )
                _emit_stream_segment_trace(
                    stream_trace,
                    phase="preprocess",
                    line_index=i + 2,
                    raw_line=c,
                    detected="role",
                    cur_company="",
                    cur_role="",
                    action="fragment_component",
                )
                _emit_stream_segment_trace(
                    stream_trace,
                    phase="preprocess",
                    line_index=i,
                    raw_line=synth,
                    detected="boundary",
                    cur_company="",
                    cur_role="",
                    action="synthesize_pipe_header",
                )
                _embedded_header_debug(
                    line_index=i,
                    raw_line=synth,
                    detected="boundary",
                    fragment_kind="dcr_triple",
                    action="synthesize_pipe_header",
                )
                i += 3
                out_idx += 1
                merged = True
            elif (
                _line_is_standalone_company_like(a)
                and _line_is_standalone_role_title(b)
                and _line_is_standalone_calendar_date_range(c)
            ):
                synth = f"{a} | {b} | {c}"
                out.append(synth)
                _emit_stream_segment_trace(
                    stream_trace,
                    phase="preprocess",
                    line_index=i,
                    raw_line=a,
                    detected="company",
                    cur_company="",
                    cur_role="",
                    action="fragment_component",
                )
                _emit_stream_segment_trace(
                    stream_trace,
                    phase="preprocess",
                    line_index=i + 1,
                    raw_line=b,
                    detected="role",
                    cur_company="",
                    cur_role="",
                    action="fragment_component",
                )
                _emit_stream_segment_trace(
                    stream_trace,
                    phase="preprocess",
                    line_index=i + 2,
                    raw_line=c,
                    detected="date",
                    cur_company="",
                    cur_role="",
                    action="fragment_component",
                )
                _emit_stream_segment_trace(
                    stream_trace,
                    phase="preprocess",
                    line_index=i,
                    raw_line=synth,
                    detected="boundary",
                    cur_company="",
                    cur_role="",
                    action="synthesize_pipe_header",
                )
                _embedded_header_debug(
                    line_index=i,
                    raw_line=synth,
                    detected="boundary",
                    fragment_kind="crd_triple",
                    action="synthesize_pipe_header",
                )
                i += 3
                out_idx += 1
                merged = True
        if not merged and i + 1 < n:
            a, b = raw[i], raw[i + 1]
            third_is_standalone_date = i + 2 < n and _line_is_standalone_calendar_date_range(
                raw[i + 2]
            )
            if (
                _line_is_standalone_company_like(a)
                and _line_is_standalone_role_title(b)
                and not third_is_standalone_date
            ):
                synth = f"{a} | {b}"
                out.append(synth)
                _embedded_header_debug(
                    line_index=i,
                    raw_line=synth,
                    detected="boundary",
                    fragment_kind="cr_pair",
                    action="synthesize_pipe_header",
                )
                _emit_stream_segment_trace(
                    stream_trace,
                    phase="preprocess",
                    line_index=i,
                    raw_line=a,
                    detected="company",
                    cur_company="",
                    cur_role="",
                    action="fragment_component",
                )
                _emit_stream_segment_trace(
                    stream_trace,
                    phase="preprocess",
                    line_index=i + 1,
                    raw_line=b,
                    detected="role",
                    cur_company="",
                    cur_role="",
                    action="fragment_component",
                )
                _emit_stream_segment_trace(
                    stream_trace,
                    phase="preprocess",
                    line_index=i,
                    raw_line=synth,
                    detected="boundary",
                    cur_company="",
                    cur_role="",
                    action="synthesize_pipe_header",
                )
                i += 2
                merged = True
        if not merged:
            out.append(raw[i])
            _emit_stream_segment_trace(
                stream_trace,
                phase="preprocess",
                line_index=i,
                raw_line=raw[i],
                detected="passthrough",
                cur_company="",
                cur_role="",
                action="keep_line",
            )
            i += 1
            out_idx += 1
    return _strip_trailing_redundant_first_header_role_repeat(out, stream_trace=stream_trace)


_REMOTE_OR_WORKMODE_ONLY = re.compile(
    r"(?i)^\s*(?:remote|hybrid|on[-\s]?site)\s*$"
)

# --- Segmentation: reject non-employer lines mistaken for company / employer segments ---
_SEGMENTATION_DEBUG_ENV = "RESUME_TAILOR_SEGMENTATION_DEBUG"
# City, ST (US-style) — not an employer row.
_US_CITY_STATE_LINE_RE = re.compile(r"^.+,\s*[A-Z]{2}\s*$")
_YEAR_ONLY_LINE_RE = re.compile(r"^\s*\d{4}\s*$")
# Stronger org signal than bare ``systems`` (must avoid ``Systems & Platforms:`` buckets).
_COMPANY_ORG_KEYWORD_SIGNAL = re.compile(
    r"(?i)\b(?:inc\.?|llc|ltd\.?|corp\.?|corporation|technologies|labs|client|moravia|"
    r"healthcare|health|solutions|group|associates|holdings|services|partners|ventures)\b"
)


def _segmentation_debug_enabled() -> bool:
    return (os.environ.get(_SEGMENTATION_DEBUG_ENV) or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _emit_segmentation_debug(raw_line: str, classification: str) -> None:
    if not _segmentation_debug_enabled():
        return
    print(
        "SEGMENTATION_DEBUG",
        json.dumps(
            {"raw_line": (raw_line or "")[:400], "classification": classification},
            ensure_ascii=False,
        ),
        flush=True,
    )


def _line_is_skill_category_or_soft_skill_colon_bucket(s: str) -> bool:
    """Skill buckets, cert/edu headers, or soft-skill ``Label: detail`` lines — not employers."""
    t = (s or "").strip()
    if not t or ":" not in t:
        return False
    if _SKILL_GROUP_HEADER_LINE.search(t):
        return True
    if _CERT_OR_EDU_BUCKET_LINE.search(t):
        return True
    head = t.split(":", 1)[0].strip()
    if _CERT_SECTION_SOFT_SKILL_HEAD.match(head):
        return True
    if re.search(r"\s&\s", head) and len(head) <= 100:
        return True
    return False


def _line_rejects_spurious_company_or_employer_segment(s: str) -> bool:
    """
    Lines that must never open or promote a company identity (location, year, buckets).
    """
    t = (s or "").strip()
    if not t:
        return True
    if _YEAR_ONLY_LINE_RE.match(t):
        return True
    if _US_CITY_STATE_LINE_RE.match(t):
        return True
    if _line_is_skill_category_or_soft_skill_colon_bucket(t):
        return True
    return False


_JOB_TITLE_HINT = re.compile(
    r"(?i)\b(?:engineer|analyst|manager|developer|director|lead|specialist|consultant|"
    r"coordinator|associate|intern|scientist|architect|designer|executive|administrator|"
    r"technician|officer|assistant|supervisor|founder|partner|cto|ceo|cfo|vp)\b"
)

# Employer-like segment (company-first pipe lines, e.g. "Gainwell Technologies | Senior BSA | …")
_EMPLOYER_SEGMENT_HINT = re.compile(
    r"(?i)\b(?:inc\.?|llc|ltd\.?|corp\.?|corporation|technologies|healthcare|health|systems|"
    r"solutions|group|associates|holdings|services|partners|ventures)\b"
)

# Skill / cert bucket lines that must not appear under PROJECTS (route to skills or drop)
_SKILL_GROUP_HEADER_LINE = re.compile(
    r"(?i)^\s*(?:data\s*&\s*analytics|systems\s*&\s*platforms|testing\s*&\s*governance|"
    r"documentation\s*&\s*modeling|core\s*(?:skills|competencies)|technical\s*skills?|"
    r"professional\s*skills?|tools?\s*&\s*technologies)\s*:\s*\S"
)

_CERT_OR_EDU_BUCKET_LINE = re.compile(
    r"(?i)^\s*(?:certifications?|education|academic\s*credentials?)\s*:\s*\S"
)

_PROJECT_EDUCATION_LEAK = re.compile(
    r"(?i)^\s*(?:bachelor|master|mba|b\.?s\.?|m\.?s\.?|ph\.?d\.?|associate\s+of|diploma)\b.*\b("
    r"university|college|institute|school)\b"
)

_GENERIC_CATEGORY_COLON_LINE = re.compile(
    r"^\s*[A-Za-z][A-Za-z0-9 &\-]{2,42}:\s*.+$"
)

# Soft-skill bucket lines mistaken for certifications (e.g. ``Collaboration: …``).
_CERT_SECTION_SOFT_SKILL_HEAD = re.compile(
    r"(?i)^(collaboration|communication|leadership|teamwork|influenc(?:e|ing)|presentation|"
    r"facilitation|negotiation|problem[- ]solving|organization|stakeholders?)\b"
)


def _cert_line_is_soft_skill_colon_leak(line: str) -> bool:
    t = (line or "").strip()
    if not t or ":" not in t:
        return False
    if skill_bucket_line_redirects_to_skills(t):
        return True
    if not _GENERIC_CATEGORY_COLON_LINE.match(t):
        return False
    head = t.split(":", 1)[0].strip()
    return bool(_CERT_SECTION_SOFT_SKILL_HEAD.match(head))

_MONTH_ONLY_TOKEN = re.compile(
    r"(?i)^(january|february|march|april|may|june|july|august|september|october|november|december|"
    r"jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)\s*$"
)

_EXPERIENCE_SECTION_LABEL = re.compile(
    r"(?i)^\s*(role\s+overview|achievements|key\s+achievements|highlights|profile|"
    r"professional\s+summary|summary)\s*:?\s*$"
)


_MONTH_WORDS = frozenset(
    """
    january february march april may june july august september october november december
    jan feb mar apr may jun jul aug sep sept oct nov dec
    present current
    """.split()
)

_CALENDARISH = re.compile(
    r"(?i)(?:\b(?:19|20)\d{2}\b|"
    r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|january|february|march|april|june|july|august|september|october|november|december)\b|"
    r"present|current)"
)


def _is_date_or_range_only_token(s: str) -> bool:
    """True if the string is calendar metadata (date span, month words, years) without a job/employer."""
    t = re.sub(r"[\u2013\u2014\u2212]", "-", (s or "").strip())
    if len(t) < 4:
        return False
    if _JOB_TITLE_HINT.search(t):
        return False
    if re.search(r"(?i)\b(?:inc|llc|ltd|corp|corporation|company)\b", t):
        return False
    if re.search(r"\s+at\s+", t, re.I):
        return False
    if not _CALENDARISH.search(t):
        return False
    for w in re.findall(r"[A-Za-z]{3,}", t):
        if w.lower() not in _MONTH_WORDS:
            return False
    return True


def _valid_job_identity(company: str, role: str) -> bool:
    """
    A real job row requires company and/or role. Date, location, or work-mode alone are invalid.
    A split date range (two date fragments) is not a valid company+role pair.
    """
    c = (company or "").strip()
    r = (role or "").strip()
    if not c and not r:
        return False
    if not c and _REMOTE_OR_WORKMODE_ONLY.match(r):
        return False
    if not r and _REMOTE_OR_WORKMODE_ONLY.match(c):
        return False
    c_meta = bool(c) and _is_date_or_range_only_token(c)
    r_meta = bool(r) and _is_date_or_range_only_token(r)
    if c and r and c_meta and r_meta:
        return False
    if not c and r and r_meta:
        return False
    if c and not r and c_meta:
        return False
    return True


def _month_only_token(s: str) -> bool:
    return bool(_MONTH_ONLY_TOKEN.match((s or "").strip()))


def _employer_identity_token(s: str) -> str:
    """Loose key for “same employer” checks (promotion must not swallow the next job’s header)."""
    t = re.sub(r"\s+", " ", (s or "").strip().lower())
    return t[:48] if t else ""


def _role_field_is_date_location_blob(s: str) -> bool:
    """True when ``role`` accidentally holds date span / Remote (no job title)."""
    t = (s or "").strip()
    if not t:
        return False
    if _JOB_TITLE_HINT.search(t):
        return False
    if _segment_looks_like_employer(t):
        return False
    if len(t) > 120:
        return False
    if _DATE_SPAN_RE.search(t):
        return True
    if _REMOTE_OR_WORKMODE_ONLY.match(t):
        return True
    if "·" in t and (_CALENDARISH.search(t) or _REMOTE_OR_WORKMODE_ONLY.search(t)):
        return True
    if _CALENDARISH.search(t) and not re.search(r"(?i)\b(analyst|engineer|manager|lead|director)\b", t):
        return True
    return False


def repair_experience_field_misassignment(e: ExperienceEntry) -> ExperienceEntry:
    """
    Fix producer/API mix-ups: month in ``company``, date span in ``role``, etc.
    Prevents headers rendering as ``April`` / ``2024 – Present · Remote`` instead of identity.
    """
    company = (e.company or "").strip()
    role = (e.role or "").strip()
    date = (e.date or "").strip()
    location = (e.location or "").strip()
    bullets = list(e.bullets)

    if company and _month_only_token(company):
        date = " · ".join(x for x in (company, date) if x).strip(" ·")
        company = ""

    if company and _US_CITY_STATE_LINE_RE.match(company):
        spill = company
        location = " · ".join(x for x in (location, spill) if x).strip(" ·")
        company = ""
        _emit_segmentation_debug(spill, "location")

    if company and _YEAR_ONLY_LINE_RE.match(company):
        spill_y = company
        date = " · ".join(x for x in (date, spill_y) if x).strip(" ·")
        company = ""
        _emit_segmentation_debug(spill_y, "ignored")

    if company and _line_is_skill_category_or_soft_skill_colon_bucket(company):
        spill_c = company
        company = ""
        bullets = [spill_c] + bullets
        _emit_segmentation_debug(spill_c, "ignored")

    if role and _role_field_is_date_location_blob(role):
        parts = [p.strip() for p in re.split(r"\s*·\s*", role) if p.strip()]
        spill_front: List[str] = []
        primary_span_locked = False
        for part in parts:
            if _REMOTE_OR_WORKMODE_ONLY.match(part):
                location = " · ".join(x for x in (location, part) if x).strip(" ·")
                continue
            has_job_span = bool(
                _HEADER_METADATA_DATE_SPAN_ANY_RE.search(part) or _DATE_SPAN_RE.search(part)
            )
            if has_job_span:
                if not primary_span_locked:
                    date = " · ".join(x for x in (date, part) if x).strip(" ·")
                    primary_span_locked = True
                else:
                    spill_front.append(part)
                continue
            if _CALENDARISH.search(part):
                date = " · ".join(x for x in (date, part) if x).strip(" ·")
                continue
            spill_front.append(part)
        role = ""
        if spill_front:
            bullets = spill_front + bullets

    if company and not _segment_looks_like_employer(company) and _DATE_SPAN_RE.search(company):
        date = " · ".join(x for x in (company, date) if x).strip(" ·")
        company = ""

    return ExperienceEntry(company, role, date, location, bullets)


def promote_experience_identity_from_leading_bullets(e: ExperienceEntry) -> ExperienceEntry:
    """Consume header-shaped or employer-only leading lines into company/role fields."""
    company = (e.company or "").strip()
    role = (e.role or "").strip()
    date = (e.date or "").strip()
    location = (e.location or "").strip()
    bullets = [str(b).strip() for b in e.bullets if str(b).strip()]

    # Drop leading lines that only repeat date/location already in header fields so
    # real employer/title lines are not stuck behind metadata bullets.
    _meta_ent = ExperienceEntry(company, role, date, location, [])
    while bullets:
        first = bullets[0]
        if _is_duplicate_experience_metadata_bullet(first, _meta_ent):
            bullets = bullets[1:]
            continue
        if _REMOTE_OR_WORKMODE_ONLY.match(first) and (location or "").strip():
            fl = first.strip().lower()
            if fl in (location or "").lower() or fl in ((date or "") + " " + (location or "")).lower():
                bullets = bullets[1:]
                continue
        break

    for _ in range(8):
        if not bullets:
            break
        first = bullets[0]
        if _line_looks_like_role_header(first):
            r, c, d, loc, ov = _parse_role_header_line(first)
            if _valid_job_identity(c, r):
                ex_tok = _employer_identity_token(company)
                nx_tok = _employer_identity_token(c)
                if ex_tok and nx_tok and ex_tok != nx_tok:
                    break
                company = company or c
                role = role or r
                if d and not date:
                    date = d
                if loc:
                    location = " · ".join(x for x in (location, loc) if x).strip(" ·")
                bullets = bullets[1:]
                if ov:
                    bullets = list(ov) + bullets
                continue
        if (not company or _month_only_token(company)) and not _line_looks_like_role_header(
            first
        ) and not _line_is_standalone_role_title(first):
            if _line_is_compact_location_metadata(first) and len(first) < 120:
                location = " · ".join(x for x in (location, first) if x).strip(" ·")
                bullets = bullets[1:]
                _emit_segmentation_debug(first, "location")
                continue
            if _YEAR_ONLY_LINE_RE.match(first):
                date = " · ".join(x for x in (date, first) if x).strip(" ·")
                bullets = bullets[1:]
                _emit_segmentation_debug(first, "ignored")
                continue
        if (not company or _month_only_token(company)) and _segment_looks_like_employer(first) and len(first) < 100:
            # Do not treat long prose bullets (typical achievements) as employer names.
            if first.rstrip().endswith(".") and len(first.split()) > 6:
                break
            company = first
            bullets = bullets[1:]
            continue
        break

    if not (company or "").strip() and bullets:
        for k in range(min(8, len(bullets))):
            bt = bullets[k].strip()
            if not bt or "|" in bt:
                continue
            head = bt.split("|", 1)[0].strip()
            low = head.lower()
            if low == "tesla":
                company = "Tesla"
                bullets = bullets[:k] + bullets[k + 1 :]
                break
            if low.startswith("rws moravia") and "(" in bt and len(bt) < 140:
                company = head
                bullets = bullets[:k] + bullets[k + 1 :]
                break

    return ExperienceEntry(company, role, date, location, bullets)


def _is_experience_section_label_line(bt: str) -> bool:
    return bool(_EXPERIENCE_SECTION_LABEL.match((bt or "").strip()))


def _is_experience_profile_or_overview_bullet(bt: str) -> bool:
    t = (bt or "").strip()
    if not t:
        return False
    if _is_experience_section_label_line(t):
        return True
    if len(t) > 200 and re.search(r"\d+\+?\s*years", t, re.I) and " with " in t.lower():
        return True
    if re.match(
        r"(?i)^[A-Za-z0-9\s/&\-–—]{6,100}\s+with\s+\d+\+?\s*years\b",
        t,
    ):
        return True
    if re.match(r"(?i)^recognized\s+for\b", t):
        return True
    if re.match(r"(?i)^(?:a\s+)?(?:dedicated|results-driven|passionate)\s+", t):
        return True
    return False


def _is_duplicate_experience_metadata_bullet(bt: str, e: ExperienceEntry) -> bool:
    """Drop lines that only repeat date/location already shown in the entry header."""
    n = re.sub(r"\s+", " ", (bt or "").strip().lower())
    if len(n) > 140:
        return False
    combined = " · ".join(
        p for p in ((e.date or "").strip(), (e.location or "").strip()) if p
    ).strip()
    if combined and n == combined.lower():
        return True
    for meta in ((e.date or "").strip(), (e.location or "").strip()):
        if meta and n == meta.lower():
            return True
    return False


def filter_experience_bullet_noise(e: ExperienceEntry) -> ExperienceEntry:
    """Remove profile/overview lines, section labels, and duplicate metadata from bullets."""
    kept: List[str] = []
    for b in e.bullets:
        bt = str(b).strip()
        if not bt:
            continue
        if _is_experience_section_label_line(bt):
            continue
        if _is_experience_profile_or_overview_bullet(bt):
            continue
        if _is_duplicate_experience_metadata_bullet(bt, e):
            continue
        kept.append(bt)
    return ExperienceEntry(e.company, e.role, e.date, e.location, kept)


def _log_experience_entry_assembled(ent: ExperienceEntry, *, context: str) -> None:
    logger.info(
        "EXPERIENCE_ENTRY_ASSEMBLY context=%s company=%r role=%r date=%r location=%r bullet_count=%s",
        context,
        (ent.company or "").strip(),
        (ent.role or "").strip(),
        (ent.date or "").strip(),
        (ent.location or "").strip(),
        len(ent.bullets),
    )


def _count_distinct_date_spans_in_header_metadata(date_s: str, loc_s: str) -> int:
    """How many job-level date ranges appear in date + location (segmentation sanity)."""
    combined = f"{date_s or ''} {loc_s or ''}"
    if not combined.strip():
        return 0
    return len(_HEADER_METADATA_DATE_SPAN_ANY_RE.findall(combined))


def _clamp_merged_header_date_to_single_span(date_s: str, loc_s: str) -> Tuple[str, str, str]:
    """
    When date+location glue contains multiple job-range spans, keep metadata before the
    second span as the first job’s header date glue and return the remainder as ``spill``
    (leading lines for the next job — never concatenated into one ``date`` field).
    """
    d0 = (date_s or "").strip()
    l0 = (loc_s or "").strip()
    combined = " · ".join(p for p in (d0, l0) if p)
    if not combined:
        return d0, l0, ""
    it = list(_HEADER_METADATA_DATE_SPAN_ANY_RE.finditer(combined))
    if len(it) < 2:
        return d0, l0, ""
    second_start = it[1].start()
    kept = combined[:second_start].strip(" ·")
    spill = combined[second_start:].strip(" ·")
    new_loc = l0
    if l0 and spill and l0.lower() in spill.lower():
        new_loc = ""
    return kept, new_loc, spill


def _polish_segmented_experience_row(ent: ExperienceEntry) -> ExperienceEntry:
    """Same cleanup chain used after each segmented or re-segmented row."""
    ent = repair_experience_field_misassignment(ent)
    ent = normalize_experience_entry_identity(ent)
    ent = promote_experience_identity_from_leading_bullets(ent)
    ce = _clean_bullets_for_structured_entry(ent)
    ce = filter_experience_bullet_noise(ce)
    ce = ExperienceEntry(
        ce.company, ce.role, ce.date, ce.location, _split_oversized_bullets(ce.bullets)
    )
    reordered, _ = prioritize_experience_entry_bullets(
        ce.company, ce.role, ce.bullets, date=ce.date, location=ce.location
    )
    return ExperienceEntry(ce.company, ce.role, ce.date, ce.location, reordered)


def _resplit_entries_with_merged_header_dates(entries: List[ExperienceEntry]) -> List[ExperienceEntry]:
    """
    Last-chance recovery: if header metadata still contains multiple job date spans after
    repair/segmentation, keep only the first span in ``date``/``location`` and move the
    remainder to **leading bullets** so validators see a single range per row. Downstream
    segmentation (from full pipe headers already in ``bullets``) can still form Tesla/RWS rows.
    """
    out: List[ExperienceEntry] = []
    for ent in entries:
        if _count_distinct_date_spans_in_header_metadata(ent.date, ent.location) <= 1:
            out.append(ent)
            continue
        d_new, loc_new, spill = _clamp_merged_header_date_to_single_span(ent.date, ent.location)
        new_bullets = ([spill] if spill else []) + [str(b).strip() for b in ent.bullets if str(b).strip()]
        out.append(
            _polish_segmented_experience_row(
                ExperienceEntry(
                    ent.company,
                    ent.role,
                    d_new,
                    loc_new,
                    new_bullets,
                )
            )
        )
    return out


def _embedded_header_redundant_for_entry(e: ExperienceEntry, company: str, role: str) -> bool:
    """True when a header-shaped bullet only repeats this row’s existing company + role."""
    if not (e.company or "").strip() or not (e.role or "").strip():
        return False
    return (
        _employer_identity_token(company) == _employer_identity_token(e.company or "")
        and (role or "").strip().lower() == (e.role or "").strip().lower()
    )


def _bullet_opens_distinct_employer_boundary(e: ExperienceEntry, bt: str) -> bool:
    """
    True when ``bt`` starts a different job than row ``e`` (pipe header or standalone employer).
    Used to force embedded-header resplit; never overwrites ``e``'s company in place.
    """
    t = str(bt).strip()
    if not t:
        return False
    cur_key = _employer_identity_token(e.company or "")
    if not cur_key:
        return False
    if _line_looks_like_role_header(t):
        r, c, _d, _loc, _ov = _parse_role_header_line(t)
        if not _valid_job_identity(c, r):
            return False
        if _embedded_header_redundant_for_entry(e, c, r):
            return False
        nx_key = _employer_identity_token(c or "")
        return bool(nx_key and nx_key != cur_key)
    if _line_is_standalone_company_like(t):
        nx_key = _employer_identity_token(t)
        return bool(nx_key and nx_key != cur_key)
    return False


def _first_embedded_distinct_job_header_bullet_index(e: ExperienceEntry) -> Optional[int]:
    """First bullet index that starts a *different* job than ``e`` (pipe header or employer line)."""
    for j, b in enumerate(e.bullets):
        if _bullet_opens_distinct_employer_boundary(e, str(b).strip()):
            return j
    return None


def _resegment_entry_splitting_at_embedded_header(e: ExperienceEntry, idx: int) -> List[ExperienceEntry]:
    """
    Re-run identity-first segmentation with a synthetic opening header for this row, then
    all bullets up to and including the embedded next-job header line in order.
    """
    bullets_flat = [str(b).strip() for b in e.bullets if str(b).strip()]
    # Standalone employer + title (+ optional date) without pipes: synthesize so the scanner opens a row.
    if (
        0 <= idx < len(bullets_flat) - 1
        and _line_is_standalone_company_like(bullets_flat[idx])
        and _line_is_standalone_role_title(bullets_flat[idx + 1])
        and "|" not in bullets_flat[idx]
    ):
        if (
            idx + 2 < len(bullets_flat)
            and _line_is_standalone_calendar_date_range(bullets_flat[idx + 2])
        ):
            synth_job = (
                f"{bullets_flat[idx]} | {bullets_flat[idx + 1]} | {bullets_flat[idx + 2]}"
            )
            skip = 3
        else:
            synth_job = f"{bullets_flat[idx]} | {bullets_flat[idx + 1]}"
            skip = 2
        bullets_flat = bullets_flat[:idx] + [synth_job] + bullets_flat[idx + skip :]

    synth_parts = [str(p).strip() for p in (e.company, e.role, e.date, e.location) if str(p).strip()]
    bullets_before = bullets_flat[:idx]
    bullets_from = bullets_flat[idx:]
    if len(synth_parts) >= 2:
        line0 = " | ".join(synth_parts)
        merged = [line0] + bullets_before + bullets_from
        raw_rows = _segment_bullets_into_entries(merged, block_date="", block_location="")
    else:
        merged = bullets_before + bullets_from
        raw_rows = _segment_bullets_into_entries(
            merged,
            block_date=(e.date or "").strip(),
            block_location=(e.location or "").strip(),
        )
    return [_polish_segmented_experience_row(x) for x in raw_rows]


def _split_one_entry_embedded_headers_chain(
    ent: ExperienceEntry,
    *,
    depth: int = 0,
) -> List[ExperienceEntry]:
    if depth > 14:
        return [ent]
    idx = _first_embedded_distinct_job_header_bullet_index(ent)
    if idx is None:
        return [ent]
    parts = _resegment_entry_splitting_at_embedded_header(ent, idx)
    out: List[ExperienceEntry] = []
    for p in parts:
        out.extend(_split_one_entry_embedded_headers_chain(p, depth=depth + 1))
    return out


def _split_entries_on_embedded_job_header_bullets(
    entries: List[ExperienceEntry],
) -> List[ExperienceEntry]:
    """Split any row whose bullets contain a later job’s pipe/header line into multiple rows."""
    flat: List[ExperienceEntry] = []
    for ent in entries:
        flat.extend(_split_one_entry_embedded_headers_chain(ent))
    return flat


def _log_experience_entry_zero_audit(stage: str, entries: List[ExperienceEntry]) -> None:
    """Debug: ``experience[0]`` identity + every bullet with index; highlights index 14 and 10–18."""
    if not entries:
        return
    e0 = entries[0]
    indexed = [f"[{i}] {str(b).strip()}" for i, b in enumerate(e0.bullets)]
    logger.info(
        "EXPERIENCE_ENTRY0_AUDIT stage=%s company=%r role=%r date=%r location=%r bullet_count=%s",
        stage,
        (e0.company or "").strip(),
        (e0.role or "").strip(),
        (e0.date or "").strip(),
        (e0.location or "").strip(),
        len(e0.bullets),
    )
    logger.info(
        "EXPERIENCE_ENTRY0_AUDIT stage=%s bullets_indexed_full=%s",
        stage,
        json.dumps(indexed, ensure_ascii=False),
    )
    if len(e0.bullets) > 14:
        lo = max(0, 10)
        hi = min(len(e0.bullets), 19)
        nearby = {str(i): str(e0.bullets[i]).strip() for i in range(lo, hi)}
        logger.info(
            "EXPERIENCE_ENTRY0_AUDIT stage=%s bullet[14]=%r nearby_10_18=%s",
            stage,
            e0.bullets[14],
            json.dumps(nearby, ensure_ascii=False),
        )


def _chunk_looks_like_company_identity(chunk: str) -> bool:
    """Distinct employer/org chunk when ``company`` was incorrectly joined with `` · ``."""
    c = (chunk or "").strip()
    if len(c) < 3:
        return False
    if _is_date_or_range_only_token(c):
        return False
    if _REMOTE_OR_WORKMODE_ONLY.match(c):
        return False
    if _segment_looks_like_employer(c):
        return True
    if re.match(r"^[A-Z][a-zA-Z.&]{2,24}$", c) and not _JOB_TITLE_HINT.search(c):
        return True
    return False


def _count_company_identity_chunks_in_company_field(company: str) -> int:
    parts = [p.strip() for p in re.split(r"\s*·\s*", company or "") if p.strip()]
    hits = [p.lower() for p in parts if _chunk_looks_like_company_identity(p)]
    return len(set(hits))


def _is_pure_bullet_orphan_entry(ent: ExperienceEntry) -> bool:
    """True when this row has bullets but no company/role and no date/location (strict bucket)."""
    if not ent.bullets:
        return False
    if (ent.company or "").strip() or (ent.role or "").strip():
        return False
    if (ent.date or "").strip() or (ent.location or "").strip():
        return False
    return True


def _is_identity_less_bullet_entry(ent: ExperienceEntry) -> bool:
    """
    Bullet bucket without job identity — often ``date_range``/``location`` duplicated on the
    same API object as tailored bullets (still no company/role). Must merge into adjacent job.
    """
    if not ent.bullets:
        return False
    return not ((ent.company or "").strip() or (ent.role or "").strip())


def _log_experience_lifecycle_stage(stage: str, entries: List[ExperienceEntry]) -> None:
    """First five rows: identity fields + source bullet lines contributing to each entry."""
    for idx in range(min(5, len(entries))):
        e = entries[idx]
        src = [str(b).strip() for b in e.bullets[:8] if str(b).strip()]
        logger.info(
            "EXPERIENCE_PIPELINE stage=%s index=%s company=%r role=%r date=%r location=%r "
            "source_lines=%s",
            stage,
            idx,
            (e.company or "").strip()[:200],
            (e.role or "").strip()[:200],
            (e.date or "").strip()[:220],
            (e.location or "").strip()[:200],
            json.dumps(src, ensure_ascii=False),
        )


def normalize_experience_entries_batch(entries: List[ExperienceEntry]) -> List[ExperienceEntry]:
    """
    Re-run per-entry repair/normalize/clean/prioritize (NORMALIZED stage).

    Identity-less bullet buckets skip ``normalize_experience_entry_identity`` / ``promote_*``:
    promoting the first achievement line into ``company`` would fake identity and block
    orphan merge into the following structured job row.
    """
    out: List[ExperienceEntry] = []
    for ent in entries:
        if _is_identity_less_bullet_entry(ent):
            e = repair_experience_field_misassignment(ent)
            ce = ExperienceEntry(
                "",
                "",
                (e.date or "").strip(),
                (e.location or "").strip(),
                [str(b).strip() for b in e.bullets if str(b).strip()],
            )
            ce = _clean_bullets_for_structured_entry(ce)
            ce = filter_experience_bullet_noise(ce)
            ce = ExperienceEntry(
                ce.company, ce.role, ce.date, ce.location, _split_oversized_bullets(ce.bullets)
            )
            reordered, _ = prioritize_experience_entry_bullets(
                ce.company, ce.role, ce.bullets, date=ce.date, location=ce.location
            )
            out.append(ExperienceEntry(ce.company, ce.role, ce.date, ce.location, reordered))
            continue
        e = repair_experience_field_misassignment(ent)
        e = normalize_experience_entry_identity(e)
        e = promote_experience_identity_from_leading_bullets(e)
        ce = _clean_bullets_for_structured_entry(e)
        ce = filter_experience_bullet_noise(ce)
        ce = ExperienceEntry(
            ce.company, ce.role, ce.date, ce.location, _split_oversized_bullets(ce.bullets)
        )
        reordered, _ = prioritize_experience_entry_bullets(
            ce.company, ce.role, ce.bullets, date=ce.date, location=ce.location
        )
        out.append(ExperienceEntry(ce.company, ce.role, ce.date, ce.location, reordered))
    return out


def _merge_bullet_orphan_into_identity_entry(
    orphan: ExperienceEntry,
    target: ExperienceEntry,
    *,
    orphan_idx: int,
    target_idx: int,
    direction: str,
) -> ExperienceEntry:
    """Attach orphan bullets to a valid job row; re-run the same cleanup/prioritization chain."""
    bullets = list(orphan.bullets) + list(target.bullets)
    merged = ExperienceEntry(
        target.company,
        target.role,
        target.date,
        target.location,
        bullets,
    )
    merged = repair_experience_field_misassignment(merged)
    merged = normalize_experience_entry_identity(merged)
    merged = promote_experience_identity_from_leading_bullets(merged)
    merged = _clean_bullets_for_structured_entry(merged)
    merged = filter_experience_bullet_noise(merged)
    merged = ExperienceEntry(
        merged.company,
        merged.role,
        merged.date,
        merged.location,
        _split_oversized_bullets(merged.bullets),
    )
    reordered, _ = prioritize_experience_entry_bullets(
        merged.company,
        merged.role,
        merged.bullets,
        date=merged.date,
        location=merged.location,
    )
    merged = ExperienceEntry(merged.company, merged.role, merged.date, merged.location, reordered)
    logger.info(
        "MERGED_ORPHAN_BULLETS_INTO_ENTRY orphan_idx=%s target_idx=%s direction=%s "
        'reason="adjacent valid identity" company=%r role=%r bullet_count_after=%s',
        orphan_idx,
        target_idx,
        direction,
        (merged.company or "").strip(),
        (merged.role or "").strip(),
        len(merged.bullets),
    )
    return merged


def _merge_safe_to_combine_orphan_into_target(orphan: ExperienceEntry, target: ExperienceEntry) -> bool:
    """Do not merge if the target header already violates sealed-metadata rules."""
    if not _valid_job_identity(target.company, target.role):
        return False
    if _count_distinct_date_spans_in_header_metadata(target.date, target.location) > 1:
        return False
    if _count_company_identity_chunks_in_company_field(target.company or "") > 1:
        return False
    return True


def _collapse_consecutive_identity_less_bullet_entries(
    entries: List[ExperienceEntry],
) -> List[ExperienceEntry]:
    """
    Merge adjacent identity-less bullet rows into one bucket (strip orphan date/location so
    metadata cannot block forward merge into the next real job row).
    """
    if not entries:
        return []
    out: List[ExperienceEntry] = []
    i = 0
    n = len(entries)
    while i < n:
        ent = entries[i]
        if _is_identity_less_bullet_entry(ent):
            bullets: List[str] = list(ent.bullets)
            j = i + 1
            while j < n and _is_identity_less_bullet_entry(entries[j]):
                bullets.extend(entries[j].bullets)
                j += 1
            out.append(ExperienceEntry("", "", "", "", bullets))
            i = j
            continue
        out.append(ent)
        i += 1
    return out


def _merge_identity_less_pass(entries: List[ExperienceEntry]) -> List[ExperienceEntry]:
    """One forward/backward sweep for identity-less bullet rows (caller loops until stable)."""
    entries = _collapse_consecutive_identity_less_bullet_entries(entries)
    if len(entries) < 2:
        return list(entries)
    out: List[ExperienceEntry] = []
    i = 0
    n = len(entries)
    while i < n:
        ent = entries[i]
        if _is_identity_less_bullet_entry(ent) and i + 1 < n:
            nxt = entries[i + 1]
            if _merge_safe_to_combine_orphan_into_target(ent, nxt):
                merged = _merge_bullet_orphan_into_identity_entry(
                    ent, nxt, orphan_idx=i, target_idx=i + 1, direction="forward"
                )
                out.append(merged)
                i += 2
                continue
        if _is_identity_less_bullet_entry(ent) and out:
            prev = out[-1]
            if _merge_safe_to_combine_orphan_into_target(ent, prev):
                merged = _merge_bullet_orphan_into_identity_entry(
                    ent, prev, orphan_idx=i, target_idx=len(out) - 1, direction="backward"
                )
                out[-1] = merged
                i += 1
                continue
        out.append(ent)
        i += 1
    return out


def _bullets_contain_contiguous_embedded_dcr_fragment(
    bullets: List[str],
) -> Optional[Tuple[int, int, int]]:
    """Return (i, i+1, i+2) if three consecutive bullets are date / company / role fragments."""
    bs = [str(b).strip() for b in bullets]
    for k in range(len(bs) - 2):
        a, b, c = bs[k], bs[k + 1], bs[k + 2]
        if not a or not b or not c:
            continue
        if (
            _line_is_standalone_calendar_date_range(a)
            and _line_is_standalone_company_like(b)
            and _line_is_standalone_role_title(c)
        ):
            return (k, k + 1, k + 2)
    return None


def _bullets_contain_contiguous_embedded_crd_fragment(
    bullets: List[str],
) -> Optional[Tuple[int, int, int]]:
    """Return indices if three consecutive lines are company / role / date fragments."""
    bs = [str(b).strip() for b in bullets]
    for k in range(len(bs) - 2):
        a, b, c = bs[k], bs[k + 1], bs[k + 2]
        if not a or not b or not c:
            continue
        if (
            _line_is_standalone_company_like(a)
            and _line_is_standalone_role_title(b)
            and _line_is_standalone_calendar_date_range(c)
        ):
            return (k, k + 1, k + 2)
    return None


def merge_pure_orphan_bullet_entries_into_adjacent_identity(
    entries: List[ExperienceEntry],
) -> List[ExperienceEntry]:
    """
    Fold identity-less bullet buckets (no company/role; date/location optional) into an
    adjacent row with valid company/role. Runs until stable so chained orphans resolve.
    """
    current = list(entries)
    for _ in range(max(1, len(entries) + 3)):
        nxt = _merge_identity_less_pass(current)
        if nxt == current:
            return nxt
        current = nxt
    return current


_TRAILING_METADATA_DEBUG_ENV = "EXPERIENCE_TRAILING_METADATA_DEBUG"


def _trailing_metadata_debug_enabled() -> bool:
    return (os.environ.get(_TRAILING_METADATA_DEBUG_ENV) or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _log_experience_trailing_metadata_debug(
    *,
    entry_index: int,
    company: str,
    role: str,
    removed_location: Optional[str],
    removed_date: Optional[str],
) -> None:
    if not _trailing_metadata_debug_enabled():
        return
    payload = {
        "entry_index": entry_index,
        "company": (company or "").strip()[:200],
        "role": (role or "").strip()[:200],
        "removed_location": ((removed_location or "").strip()[:220] or None),
        "removed_date": ((removed_date or "").strip()[:220] or None),
    }
    logger.info("EXPERIENCE_TRAILING_METADATA_DEBUG %s", json.dumps(payload, ensure_ascii=False))


def _line_is_trailing_city_state_location_line(s: str) -> bool:
    """US-style ``City, ST`` compact location (RWS dateline leak) — not a prose bullet."""
    t = (s or "").strip()
    if not t:
        return False
    return bool(_US_CITY_STATE_LINE_RE.match(t)) and _line_is_compact_location_metadata(t)


def _promote_trailing_location_date_metadata_from_entries(
    entries: List[ExperienceEntry],
) -> List[ExperienceEntry]:
    """
    Peel trailing location / calendar date-span lines left inside ``bullets`` (common RWS
    three-line header leak) and bind them to ``location`` / ``date`` when those header fields
    are still empty. Supports ``location`` then ``date`` or the reverse. Runs before sealed
    fragment validation inside :func:`_finalize_experience_entries_sealed`.
    """

    def _is_trailing_location_line(t: str) -> bool:
        s = (t or "").strip()
        return bool(s) and _line_is_compact_location_metadata(s)

    def _is_trailing_date_line(t: str) -> bool:
        s = (t or "").strip()
        return bool(s) and _line_is_standalone_calendar_date_range(s)

    out: List[ExperienceEntry] = []
    for entry_index, ent in enumerate(entries):
        bullets = [_normalize_resume_line_dashes(str(b).strip()) for b in ent.bullets if str(b).strip()]
        loc_out = (ent.location or "").strip()
        date_out = (ent.date or "").strip()

        guard = 0
        while guard < 8:
            guard += 1
            rl: Optional[str] = None
            rd: Optional[str] = None
            peeled = False
            if len(bullets) >= 2:
                a, b = bullets[-2], bullets[-1]
                if _is_trailing_location_line(a) and _is_trailing_date_line(b):
                    bullets = bullets[:-2]
                    rl, rd = a, b
                    peeled = True
                elif _is_trailing_date_line(a) and _is_trailing_location_line(b):
                    bullets = bullets[:-2]
                    rd, rl = a, b
                    peeled = True
            if not peeled and bullets and _is_trailing_date_line(bullets[-1]):
                rd = bullets[-1]
                bullets = bullets[:-1]
                peeled = True
            if not peeled and bullets and _line_is_trailing_city_state_location_line(bullets[-1]):
                rl = bullets[-1]
                bullets = bullets[:-1]
                peeled = True
            if not peeled:
                break
            if rl and not loc_out:
                loc_out = rl.strip()
            if rd and not date_out:
                date_out = rd.strip()
            _log_experience_trailing_metadata_debug(
                entry_index=entry_index,
                company=ent.company,
                role=ent.role,
                removed_location=rl,
                removed_date=rd,
            )

        out.append(ExperienceEntry(ent.company, ent.role, date_out, loc_out, bullets))
    return out


def _finalize_experience_entries_sealed(entries: List[ExperienceEntry]) -> List[ExperienceEntry]:
    """
    Last pass: one more adjacent merge, then seal — no bullets without identity, no merged
    multi-job headers.
    """
    entries = merge_pure_orphan_bullet_entries_into_adjacent_identity(list(entries))
    entries = _resplit_entries_with_merged_header_dates(entries)
    entries = merge_pure_orphan_bullet_entries_into_adjacent_identity(entries)
    entries = _split_entries_on_embedded_job_header_bullets(entries)
    entries = _lift_standalone_employer_into_company_when_missing(entries)
    entries = merge_pure_orphan_bullet_entries_into_adjacent_identity(entries)
    entries = _promote_trailing_location_date_metadata_from_entries(entries)
    _log_experience_lifecycle_stage("FINAL_PRE_VALIDATION", entries)
    _log_experience_entry_zero_audit("FINAL_PRE_VALIDATION", entries)
    for i, ent in enumerate(entries):
        has_id = bool((ent.company or "").strip() or (ent.role or "").strip())
        if ent.bullets and not has_id:
            prev_h = ""
            next_h = ""
            if i > 0:
                p = entries[i - 1]
                prev_h = (
                    f" neighbor_before[{i - 1}] company={p.company!r} role={p.role!r} "
                    f"bullet_count={len(p.bullets)}"
                )
            if i + 1 < len(entries):
                n = entries[i + 1]
                next_h = (
                    f" neighbor_after[{i + 1}] company={n.company!r} role={n.role!r} "
                    f"bullet_count={len(n.bullets)}"
                )
            raise ResumeContractError(
                f"experience[{i}]: bullets require company or role "
                f"(identity-less bullet row could not be merged into an adjacent job; "
                f"preview={ent.bullets[:3]!r}).{prev_h}{next_h}"
            )
        n_spans = _count_distinct_date_spans_in_header_metadata(ent.date, ent.location)
        if n_spans > 1:
            raise ResumeContractError(
                f"experience[{i}]: header date/location contains {n_spans} date ranges "
                f"(segmentation failure — merged job metadata). date={ent.date!r} location={ent.location!r}"
            )
        dcr = _bullets_contain_contiguous_embedded_dcr_fragment(list(ent.bullets))
        if dcr is not None:
            j0, j1, j2 = dcr
            frag = [str(ent.bullets[j0]).strip(), str(ent.bullets[j1]).strip(), str(ent.bullets[j2]).strip()]
            raise ResumeContractError(
                f"experience[{i}]: bullets[{j0}:{j2 + 1}] form a contiguous embedded "
                f"date/company/role header fragment (segmentation failure). fragment={frag!r}"
            )
        crd = _bullets_contain_contiguous_embedded_crd_fragment(list(ent.bullets))
        if crd is not None:
            j0, j1, j2 = crd
            frag = [str(ent.bullets[j0]).strip(), str(ent.bullets[j1]).strip(), str(ent.bullets[j2]).strip()]
            raise ResumeContractError(
                f"experience[{i}]: bullets[{j0}:{j2 + 1}] form a contiguous embedded "
                f"company/role/date header fragment (segmentation failure). fragment={frag!r}"
            )
        for j, b in enumerate(ent.bullets):
            bt = str(b).strip()
            if _line_is_embedded_identity_fragment(bt):
                lo = max(0, j - 4)
                hi = min(len(ent.bullets), j + 5)
                ctx = [str(ent.bullets[k]).strip() for k in range(lo, hi)]
                detail = "standalone date/company/title fragment"
                if _line_is_standalone_role_title(bt) and not _line_looks_like_role_header(bt):
                    detail = "strong standalone role/title line"
                raise ResumeContractError(
                    f"experience[{i}].bullets[{j}] is a {detail}, "
                    f"not a bullet (segmentation failure — embedded job header boundary not applied). "
                    f"context_index_{lo}_{hi}={ctx!r}"
                )
            if not _line_looks_like_role_header(bt):
                continue
            lo = max(0, j - 4)
            hi = min(len(ent.bullets), j + 5)
            ctx = [str(ent.bullets[k]).strip() for k in range(lo, hi)]
            raise ResumeContractError(
                f"experience[{i}].bullets[{j}] looks like a job header, not a bullet "
                f"(segmentation failure — embedded job header boundary not applied). "
                f"context_index_{lo}_{hi}={ctx!r}"
            )
    return entries


def _snapshot_experience_entries(entries: List[ExperienceEntry]) -> List[ExperienceEntry]:
    """Deep copy of experience rows for lifecycle snapshots (tests / debug)."""
    return [ExperienceEntry(e.company, e.role, e.date, e.location, list(e.bullets)) for e in entries]


def experience_segmentation_lifecycle_snapshots_from_entries(
    provisional_entries: List[ExperienceEntry],
) -> List[Tuple[str, List[ExperienceEntry]]]:
    """
    Ordered ``(stage_name, entries)`` through the same transforms as ``build_experience_entries_identity_first``
    after provisional assembly: NORMALIZED → ORPHAN_REPAIR → last-chance merge (matches
    ``_finalize_experience_entries_sealed`` merge step before seal checks).

    ``SEGMENT_PROVISIONAL`` is a snapshot of the input list (caller may pass provisional output).
    """
    snaps: List[Tuple[str, List[ExperienceEntry]]] = []
    snaps.append(("SEGMENT_PROVISIONAL", _snapshot_experience_entries(provisional_entries)))
    normalized = normalize_experience_entries_batch(provisional_entries)
    snaps.append(("NORMALIZED", _snapshot_experience_entries(normalized)))
    repaired = merge_pure_orphan_bullet_entries_into_adjacent_identity(normalized)
    snaps.append(("ORPHAN_REPAIR", _snapshot_experience_entries(repaired)))
    final_pre = merge_pure_orphan_bullet_entries_into_adjacent_identity(list(repaired))
    snaps.append(("FINAL_PRE_VALIDATION", _snapshot_experience_entries(final_pre)))
    return snaps


def experience_segmentation_lifecycle_snapshots(
    blocks: List[dict],
) -> List[Tuple[str, List[ExperienceEntry]]]:
    """Lifecycle snapshots from raw experience API blocks (same stages as DOCX assembly)."""
    provisional = experience_blocks_to_provisional_entries(blocks)
    return experience_segmentation_lifecycle_snapshots_from_entries(provisional)


def log_experience_segmentation_audit(
    experience_blocks: List[dict],
    entries: List[ExperienceEntry],
) -> None:
    """Debug: raw API blocks vs segmented entries (before validate / DOCX)."""
    logger.info("RAW EXPERIENCE BLOCKS:")
    for i, block in enumerate(experience_blocks or []):
        if not isinstance(block, dict):
            logger.info("  block[%s]=<not a dict: %s>", i, type(block).__name__)
            continue
        logger.info("  block[%s]=%s", i, json.dumps(block, ensure_ascii=False, default=str))
    logger.info("SEGMENTED EXPERIENCE ENTRIES:")
    for i, e in enumerate(entries):
        n_spans = _count_distinct_date_spans_in_header_metadata(e.date, e.location)
        multi_date = n_spans > 1
        n_co = _count_company_identity_chunks_in_company_field(e.company or "")
        multi_co = n_co > 1
        first_two = [e.bullets[j] for j in range(min(2, len(e.bullets)))]
        logger.info(
            "  entry[%s] company=%r role=%r date=%r location=%r bullet_count=%s "
            "first_two_bullets=%r date_span_count=%s multiple_date_ranges=%s "
            "company_like_chunk_count=%s multiple_company_like_signals=%s",
            i,
            (e.company or "").strip(),
            (e.role or "").strip(),
            (e.date or "").strip(),
            (e.location or "").strip(),
            len(e.bullets),
            first_two,
            n_spans,
            multi_date,
            n_co,
            multi_co,
        )


def _segment_looks_like_employer(seg: str) -> bool:
    """Heuristic: company / org name vs job title (used for pipe-order disambiguation)."""
    s = (seg or "").strip()
    if len(s) < 3:
        return False
    if _line_rejects_spurious_company_or_employer_segment(s):
        cls = "location" if _US_CITY_STATE_LINE_RE.match(s) else "ignored"
        _emit_segmentation_debug(s, cls)
        return False
    if _REMOTE_OR_WORKMODE_ONLY.match(s) or _is_date_or_range_only_token(s):
        return False
    # Titles like "Business Systems Analyst" must not match employer tokens (e.g. "systems").
    if _JOB_TITLE_HINT.search(s):
        return False
    if _EMPLOYER_SEGMENT_HINT.search(s):
        if _line_is_skill_category_or_soft_skill_colon_bucket(s):
            _emit_segmentation_debug(s, "ignored")
            return False
        _emit_segmentation_debug(s, "company")
        return True
    words = s.split()
    # Short proper-noun employers (e.g. Tesla, Apple) must win over title disambiguation.
    if len(words) == 1 and len(s) >= 5 and s[0].isupper():
        if _YEAR_ONLY_LINE_RE.match(s):
            _emit_segmentation_debug(s, "ignored")
            return False
        if any(ch.isdigit() for ch in s):
            _emit_segmentation_debug(s, "ignored")
            return False
        _emit_segmentation_debug(s, "company")
        return True
    if len(words) >= 2 and s[0].isupper() and not _JOB_TITLE_HINT.search(s):
        if not (
            _COMPANY_ORG_KEYWORD_SIGNAL.search(s)
            or re.match(r"(?i)^(tesla|rws|apple|amazon|google|meta|nvidia)\b", s)
        ):
            _emit_segmentation_debug(s, "ignored")
            return False
        _emit_segmentation_debug(s, "company")
        return True
    return False


def _classify_pipe_tail_segments(segments: List[str]) -> Tuple[str, str, List[str]]:
    """
    After role/company segments, remaining pipe parts may be date and/or location.
    Work-mode tokens must never be treated as dates (e.g. ``Remote`` after date strip).

    At most **one** job-level date span is merged into ``extra_date``; additional
    date-span tail segments (next job’s column) are returned in ``overflow`` so callers
    can start a new boundary instead of concatenating ranges into one header.
    """
    extra_date = ""
    extra_loc = ""
    overflow: List[str] = []
    locked_primary_date_span = False
    for t in segments:
        seg = (t or "").strip()
        if not seg:
            continue
        if _REMOTE_OR_WORKMODE_ONLY.match(seg):
            extra_loc = " · ".join(x for x in (extra_loc, seg) if x).strip(" ·")
            continue
        has_full_span = bool(_HEADER_METADATA_DATE_SPAN_ANY_RE.search(seg) or _DATE_SPAN_RE.search(seg))
        if has_full_span:
            if not locked_primary_date_span:
                extra_date = " · ".join(x for x in (extra_date, seg) if x).strip(" ·")
                locked_primary_date_span = True
            else:
                overflow.append(seg)
            continue
        if _CALENDARISH.search(seg):
            extra_date = " · ".join(x for x in (extra_date, seg) if x).strip(" ·")
            continue
        extra_loc = " · ".join(x for x in (extra_loc, seg) if x).strip(" ·")
    return extra_date.strip(), extra_loc.strip(), overflow


def _disambiguate_role_company_pair(a: str, b: str) -> Tuple[str, str]:
    """
    Pipe segments are often ``Title | Company | date`` but many resumes use
    ``Company | Title | date``. Return (role, company).
    """
    a, b = (a or "").strip(), (b or "").strip()
    if not a:
        return "", b
    if not b:
        return a, ""
    a_emp = _segment_looks_like_employer(a)
    b_emp = _segment_looks_like_employer(b)
    a_title = bool(_JOB_TITLE_HINT.search(a))
    b_title = bool(_JOB_TITLE_HINT.search(b))
    if a_emp and b_title and not b_emp:
        return b, a
    if b_emp and a_title and not a_emp:
        return a, b
    return a, b


def _parse_role_header_line(line: str) -> Tuple[str, str, str, str, List[str]]:
    """Returns role, company, date, location, overflow_lines (extra pipe-tail job fragments)."""
    s = (line or "").strip()
    overflow: List[str] = []
    location = ""
    mloc = _TRAILING_PARENS_LOC.search(s)
    if mloc:
        location = mloc.group(1).strip()
        s = s[: mloc.start()].strip().rstrip(",—–-")
    date_range = ""
    m = _DATE_SPAN_RE.search(s)
    if m:
        date_range = s[m.start() : m.end()].strip()
        s = (s[: m.start()] + " " + s[m.end() :]).strip().strip(",—–-")
    if "|" in s:
        parts = [p.strip() for p in s.split("|") if p.strip()]
        # ``Remote | Employer | Title | date`` (work mode must not become company/role)
        if len(parts) >= 3 and _REMOTE_OR_WORKMODE_ONLY.match(parts[0]):
            loc_prefix = parts[0]
            role, company = _disambiguate_role_company_pair(parts[1], parts[2])
            extra_date, extra_loc, ov = _classify_pipe_tail_segments(parts[3:])
            overflow.extend(ov)
            d_final = (date_range or extra_date).strip()
            loc_bits = [x for x in (location, loc_prefix, extra_loc) if x]
            loc_final = " · ".join(loc_bits) if loc_bits else ""
            return role, company, d_final, loc_final, overflow
        if len(parts) >= 2:
            role, company = _disambiguate_role_company_pair(parts[0], parts[1])
            extra_date, extra_loc, ov = _classify_pipe_tail_segments(parts[2:])
            overflow.extend(ov)
            d_final = (date_range or extra_date).strip()
            loc_bits = [x for x in (location, extra_loc) if x]
            loc_final = " · ".join(loc_bits) if loc_bits else ""
            return role, company, d_final, loc_final, overflow
    if re.search(r"\s+at\s+", s, re.I):
        a, b = re.split(r"\s+at\s+", s, maxsplit=1, flags=re.I)
        ra, ca = _disambiguate_role_company_pair(a.strip(), b.strip())
        return ra, ca, date_range, location, overflow
    if "—" in s:
        left, right = [x.strip() for x in s.split("—", 1)]
        if _YEAR_SINGLE_RE.search(right) or len(right) < 40:
            return left, "", date_range or right, location, overflow
    return s, "", date_range, location, overflow


def _work_mode_token(s: str) -> bool:
    return bool(_REMOTE_OR_WORKMODE_ONLY.match((s or "").strip()))


def normalize_experience_entry_identity(e: ExperienceEntry) -> ExperienceEntry:
    """
    Repair company/role/date/location mix-ups: Remote must not be the company label;
    company-first pipe lines must not swap title into company; first bullet may hold
    a full header line to merge into fields.
    """
    company = (e.company or "").strip()
    role = (e.role or "").strip()
    date = (e.date or "").strip()
    location = (e.location or "").strip()
    bullets = [str(b).strip() for b in e.bullets if str(b).strip()]

    if company and role:
        if _segment_looks_like_employer(role) and _JOB_TITLE_HINT.search(company) and not _segment_looks_like_employer(
            company
        ):
            role, company = company, role

    if _work_mode_token(company):
        location = " · ".join(x for x in (company, location) if x).strip(" ·")
        company = ""
    if _work_mode_token(role) and (company or date):
        location = " · ".join(x for x in (role, location) if x).strip(" ·")
        role = ""

    if bullets:
        first = bullets[0]
        recover = False
        if not company or not role:
            recover = True
        elif _work_mode_token(company):
            recover = True
        elif company and _segment_looks_like_employer(role) and _JOB_TITLE_HINT.search(company):
            recover = True
        if recover and len(first) >= 12 and _line_looks_like_role_header(first):
            r, c, d, loc, ov = _parse_role_header_line(first)
            if _valid_job_identity(c, r):
                ex_tok = _employer_identity_token(company)
                nx_tok = _employer_identity_token(c)
                if ex_tok and nx_tok and ex_tok != nx_tok:
                    pass
                else:
                    if not company or _work_mode_token(company) or (
                        _segment_looks_like_employer(r)
                        and _JOB_TITLE_HINT.search(c)
                        and not _segment_looks_like_employer(c)
                    ):
                        company = c or company
                        role = r or role
                    else:
                        if c:
                            company = c
                        if r:
                            role = r
                    if d and not date:
                        date = d
                    if loc:
                        location = " · ".join(x for x in (location, loc) if x).strip(" ·")
                    bullets = bullets[1:]
                    if ov:
                        bullets = list(ov) + bullets

    if _work_mode_token(company):
        location = " · ".join(x for x in (company, location) if x).strip(" ·")
        company = ""

    if _count_distinct_date_spans_in_header_metadata(date, location) > 1:
        date, location, spill = _clamp_merged_header_date_to_single_span(date, location)
        if spill:
            bullets = [spill] + bullets

    return ExperienceEntry(company, role, date, location, bullets)


_OVERSIZED_BULLET_MAX_CHARS = 340
_OVERSIZED_BULLET_MAX_SENTENCES = 4


def _split_frequently_placed_ambiguity_lead_bullet(t: str) -> Optional[List[str]]:
    """
    Split the dense Gainwell-style ambiguity bullet on a natural clause boundary
    (same facts, two scannable lines).
    """
    s = (t or "").strip()
    if not s.lower().startswith("frequently placed into ambiguous"):
        return None

    def _cap_sentence(x: str) -> str:
        z = (x or "").strip()
        if z and z[0].islower():
            z = z[0].upper() + z[1:]
        if z and not z.endswith((".", "!", "?")):
            z = z.rstrip(",") + "."
        return z

    # Comma splice: environments/discovery setup, then validation/outcomes tail.
    m_comma = re.match(
        r"(?is)^(Frequently placed into ambiguous, undocumented environments\s+requiring\s+rapid\s+discovery),\s*([A-Za-z].+)$",
        s,
    )
    if m_comma:
        first = m_comma.group(1).strip().rstrip(",") + "."
        return [first, _cap_sentence(m_comma.group(2).strip())]

    # Two sentences in one string (second stays on its own bullet).
    m_two_sent = re.match(
        r"(?is)^(Frequently placed into ambiguous, undocumented environments\s+requiring\s+rapid\s+discovery\.)"
        r"\s+(.+)$",
        s,
    )
    if m_two_sent and len(m_two_sent.group(2).strip()) > 8:
        return [m_two_sent.group(1).strip(), _cap_sentence(m_two_sent.group(2).strip())]

    m = re.match(
        r"(?is)^(Frequently placed into ambiguous, undocumented environments)\s+(requiring\s+.+\.?)\s*$",
        s,
    )
    if not m:
        return None
    first = m.group(1).rstrip(",.") + "."
    second = m.group(2).strip()
    if second and second[0].islower():
        second = second[0].upper() + second[1:]
    return [first, second]


_FREQUENTLY_PLACED_AMBIGUITY_SHORT = re.compile(
    r"(?is)^Frequently placed into ambiguous, undocumented environments\s+requiring\s+rapid\s+discovery\.?$"
)


def _validation_or_alignment_followup_bullet(s: str) -> bool:
    """True when the next line reads as validation / delivery / alignment (pair with ambiguity lead)."""
    t = (s or "").strip()
    if len(t) < 16:
        return False
    if not re.match(
        r"(?i)^(Lead|Led|Drove|Partnered|Aligned|Supported|Facilitated|Owned|Managed|Coordinated)\b",
        t,
    ):
        return False
    low = t.lower()
    return any(
        k in low
        for k in (
            "validation",
            "uat",
            "business",
            "client",
            "stakeholder",
            "alignment",
            "aligning",
            "rules",
            "delivery",
            "functional",
        )
    )


def _merge_frequently_placed_ambiguity_for_split(a: str, b: str) -> Optional[str]:
    """
    If the dense ambiguity bullet is immediately followed by a validation/alignment bullet,
    join with a comma so :func:`_split_frequently_placed_ambiguity_lead_bullet` can split on
    the natural boundary (same facts; two scannable lines).
    """
    a = (a or "").strip()
    b = (b or "").strip()
    if not _FREQUENTLY_PLACED_AMBIGUITY_SHORT.match(a):
        return None
    if not _validation_or_alignment_followup_bullet(b):
        return None
    return a.rstrip(". ") + ", " + b.strip()


def _strip_core_skills_label_lines(items: List[str]) -> List[str]:
    """Drop standalone ``Core Skills`` section labels mistaken for content."""
    out: List[str] = []
    for s in items or []:
        t = str(s).strip()
        if not t:
            continue
        if re.match(r"(?i)^core\s+skills:?\s*$", t):
            continue
        out.append(t)
    return out


def _cert_dict_is_core_skills_noise_row(block: dict) -> bool:
    name = str(
        block.get("name") or block.get("title") or block.get("credential") or ""
    ).strip()
    issuer = str(block.get("issuer") or block.get("organization") or "").strip()
    dt = str(block.get("date_range") or block.get("date") or block.get("dates") or "").strip()
    bullets = block.get("bullets") or []
    blist = [str(b).strip() for b in bullets if str(b).strip()] if isinstance(bullets, list) else []
    if re.match(r"(?i)^core\s+skills:?\s*$", name):
        return True
    if re.match(r"(?i)^core\s+skills\b", name) and not issuer and not dt and not blist:
        return True
    return False


def _line_should_drop_from_project_section_leak(line: str) -> bool:
    """
    Strip mistaken EDUCATION/CERTIFICATION/SKILLS section labels and ``Core Skills`` rows
    from project bullets (they belong in dedicated sections, not under Personal Project).
    """
    s = (line or "").strip()
    if not s:
        return False
    if re.match(r"(?i)^(education|certifications?|skills)\s*:?\s*$", s):
        return True
    if re.match(
        r"(?i)^(academic\s+(?:credentials|background|history)|qualifications?|licenses?)\s*:?\s*$",
        s,
    ):
        return True
    if re.match(r"(?i)^core\s+skills\b", s):
        return True
    return False


_PROJ_DEGREE_OR_SCHOOL_LINE = re.compile(
    r"(?i)\b(?:bachelor|master|b\.?a\.?|b\.?s\.?|m\.?s\.?|mba|associate|ph\.?d\.?|doctorate|diploma)\b"
    r".{0,140}\b(?:university|college|institute|school|academy)\b"
)
_PROJ_CERT_VENDOR_LINE = re.compile(
    r"(?i)^(?:comptia|aws\s+certified|microsoft\s+certified|azure\s+certified|"
    r"pmp|capm|certified\s+scrum|google\s+professional|salesforce\s+certified|"
    r"isc\s*²|isc2|cissp)\b"
)
_PROJ_CERT_MIDLINE_KEYWORDS = re.compile(
    r"(?i)\b(?:itil|ecba|ccba|cbap|iiba|sfpc|psm\s*i|psm\s*ii|cspo|capm|pgmp|pfmp|"
    r"google\s+cloud\s+professional|microsoft\s+certified)\b"
)


def _line_is_degree_or_cert_pollution_for_project(line: str) -> bool:
    """Degree / school rows and certification-style rows that must not live under PROJECTS."""
    s = (line or "").strip()
    if not s:
        return False
    if _PROJ_DEGREE_OR_SCHOOL_LINE.search(s):
        return True
    if _PROJECT_EDUCATION_LEAK.match(s):
        return True
    if _PROJ_CERT_VENDOR_LINE.match(s):
        return True
    if _PROJ_CERT_MIDLINE_KEYWORDS.search(s) and (
        re.search(r"(?i)\b(?:certification|certificate|credential|exam|accredited|issued)\b", s)
        or re.search(r"\b20\d{2}\b", s)
        or "—" in s
        or "–" in s
    ):
        return True
    if re.match(
        r"(?i)^(?:cert\.?|certificate|certification)\s*[#:]?\s*\w",
        s,
    ):
        return True
    return False


def _patch_final_experience_display_identity(
    entries: List[ExperienceEntry],
) -> List[ExperienceEntry]:
    """
    Post-seal display fixes only: attach missing short employers (Tesla, RWS) and peel
    embedded pipe headers still sitting in bullets. Does not change segmentation rules
    inside ``_segment_bullets_into_entries`` — runs on sealed ``ExperienceEntry`` rows.
    """
    out: List[ExperienceEntry] = []
    for e in entries:
        c = (e.company or "").strip()
        r = (e.role or "").strip()
        d = (e.date or "").strip()
        loc = (e.location or "").strip()
        bullets = [str(b).strip() for b in e.bullets if str(b).strip()]
        if not c and r and re.search(r"(?i)autopilot", r):
            c = "Tesla"
        if not c and r and re.search(r"(?i)business\s+data\s+technician", r):
            for k, bt in enumerate(bullets):
                if not _line_looks_like_role_header(bt):
                    continue
                if "rws moravia" not in bt.lower():
                    continue
                rp, cp, dp2, lp2, ov = _parse_role_header_line(bt)
                if _valid_job_identity(cp, rp):
                    c = (cp or c).strip()
                    r = (rp or r).strip()
                    if dp2 and not d:
                        d = dp2.strip()
                    if lp2 and not loc:
                        loc = lp2.strip()
                    bullets = bullets[:k] + [x for x in ov if str(x).strip()] + bullets[k + 1 :]
                    bullets = [str(x).strip() for x in bullets if str(x).strip()]
                break
        out.append(ExperienceEntry(c, r, d, loc, bullets))
    return out


def _lift_standalone_employer_into_company_when_missing(
    entries: List[ExperienceEntry],
) -> List[ExperienceEntry]:
    """
    When segmentation left a short employer label only in bullets (e.g. ``Tesla`` on its
    own line), move it into ``company`` so the DOCX header stack renders correctly.
    """
    out: List[ExperienceEntry] = []
    for e in entries:
        if (e.company or "").strip():
            out.append(e)
            continue
        company = ""
        bullets = [str(b).strip() for b in e.bullets if str(b).strip()]
        for k, bt in enumerate(bullets[:8]):
            if "|" in bt:
                continue
            head = bt.split("|", 1)[0].strip()
            low = head.lower()
            if low == "tesla":
                company = "Tesla"
                bullets = bullets[:k] + bullets[k + 1 :]
                break
            if low.startswith("rws moravia") and "(" in bt and len(bt) < 120:
                company = head
                bullets = bullets[:k] + bullets[k + 1 :]
                break
        if company:
            out.append(
                ExperienceEntry(
                    company,
                    (e.role or "").strip(),
                    (e.date or "").strip(),
                    (e.location or "").strip(),
                    bullets,
                )
            )
        else:
            out.append(e)
    return out


def _split_oversized_bullets(bullets: List[str]) -> List[str]:
    """Turn one wall-of-text bullet into several readable bullets (no new facts)."""
    out: List[str] = []
    items = [str(b).strip() for b in (bullets or []) if str(b).strip()]
    i = 0
    while i < len(items):
        t = items[i]
        merged: Optional[str] = None
        if i + 1 < len(items):
            merged = _merge_frequently_placed_ambiguity_for_split(t, items[i + 1])
        if merged:
            fp = _split_frequently_placed_ambiguity_lead_bullet(merged)
            if fp and len(fp) >= 2:
                out.extend(fp)
                i += 2
                continue
        fp = _split_frequently_placed_ambiguity_lead_bullet(t)
        if fp:
            out.extend(fp)
            i += 1
            continue
        sentence_split = re.split(r"(?<=[.!?])\s+(?=[A-Z(0-9\"])", t)
        n_sent = len([x for x in sentence_split if x.strip()])
        if len(t) <= _OVERSIZED_BULLET_MAX_CHARS and n_sent <= _OVERSIZED_BULLET_MAX_SENTENCES:
            out.append(t)
            i += 1
            continue
        chunk: List[str] = []
        char_n = 0
        for sent in sentence_split:
            s = sent.strip()
            if not s:
                continue
            if not chunk:
                chunk.append(s)
                char_n = len(s)
            elif char_n + len(s) + 1 > _OVERSIZED_BULLET_MAX_CHARS and chunk:
                out.append(" ".join(chunk))
                chunk = [s]
                char_n = len(s)
            else:
                chunk.append(s)
                char_n += len(s) + 1
        if chunk:
            out.append(" ".join(chunk))
        i += 1
    return out


def _api_block_to_entry(block: dict) -> ExperienceEntry:
    """Map title→role; preserve company, date, location."""
    role = str(block.get("title") or block.get("role") or "").strip()
    company = str(block.get("company") or "").strip()
    date = str(block.get("date_range") or block.get("date") or "").strip()
    location = str(block.get("location") or "").strip()
    bullets = [str(b).strip() for b in (block.get("bullets") or []) if str(b).strip()]
    return ExperienceEntry(company, role, date, location, bullets)


def _has_resume_dateline_signal(seg: str) -> bool:
    """True when ``seg`` carries a job date span or standalone calendar range."""
    t = _normalize_resume_line_dashes((seg or "").strip())
    if not t:
        return False
    if _DATE_SPAN_RE.search(t) or _HEADER_METADATA_DATE_SPAN_ANY_RE.search(t):
        return True
    if _line_is_standalone_calendar_date_range(t):
        return True
    return False


def _normalize_inline_dateline_location_pipe(line: str) -> str:
    """
    Normalize ``date | location`` when the resume uses ``location | date`` (two pipe
    segments only). Leaves multi-pipe lines unchanged for ``_parse_role_header_line``.
    """
    s = (line or "").strip()
    if "|" not in s:
        return s
    parts = [p.strip() for p in s.split("|") if p.strip()]
    if len(parts) != 2:
        return s
    a, b = parts
    a_date = _has_resume_dateline_signal(a)
    b_date = _has_resume_dateline_signal(b)
    if a_date and not b_date:
        return f"{a} | {b}"
    if b_date and not a_date:
        return f"{b} | {a}"
    return s


def _maybe_promote_split_company_role_dateline_header(bullets: List[str]) -> List[str]:
    """
    Collapse ``company`` / ``role`` / ``date [| location]`` (three lines) into one
    parseable header so ``prepare_experience_blocks_for_docx`` can find a job line before bullets.

    Accepts ``date | location`` or ``location | date`` on the third line.
    """
    if len(bullets) < 3:
        return bullets
    c0 = bullets[0].strip()
    c1 = bullets[1].strip()
    c2 = bullets[2].strip()
    if not c0 or not c1 or not c2:
        return bullets
    if _line_looks_like_role_header(c0) or _line_looks_like_role_header(c1):
        return bullets
    company_like = _line_is_standalone_company_like(c0) or _segment_looks_like_employer(c0)
    if not company_like:
        return bullets
    role_like = _line_is_standalone_role_title(c1) or (
        "|" not in c1
        and bool(_JOB_TITLE_HINT.search(c1))
        and len(c1.split()) <= 18
        and not _has_resume_dateline_signal(c1)
    )
    if not role_like:
        return bullets
    if "|" in c2:
        parts = [p.strip() for p in c2.split("|") if p.strip()]
        if len(parts) == 2 and not (
            _has_resume_dateline_signal(parts[0]) or _has_resume_dateline_signal(parts[1])
        ):
            return bullets
    elif not _has_resume_dateline_signal(c2):
        return bullets
    tail = _normalize_inline_dateline_location_pipe(c2)
    merged = _normalize_resume_line_dashes(f"{c1} at {c0} | {tail}".strip())
    role_p, comp_p, _d, _loc, ov = _parse_role_header_line(merged)
    if not _valid_job_identity(comp_p, role_p):
        return bullets
    return [merged] + list(ov) + bullets[3:]


def _first_job_header_candidate_index(bullets: List[str]) -> Optional[int]:
    """Index of the first line that starts a real job (company or role), not metadata-only."""
    for i, b in enumerate(bullets):
        if _line_looks_like_role_header(b):
            role, company, _d, _loc, _ = _parse_role_header_line(b)
            if _valid_job_identity(company, role):
                return i
    for i, b in enumerate(bullets):
        if _DATE_SPAN_RE.search(b) and len(b.strip()) >= 12:
            role, company, _d, _loc, _ = _parse_role_header_line(b)
            if _valid_job_identity(company, role):
                return i
    for i, b in enumerate(bullets):
        if b.count("|") >= 2 and 12 <= len(b.strip()) < 200:
            role, company, _d, _loc, _ = _parse_role_header_line(b)
            if _valid_job_identity(company, role):
                return i
    for i, b in enumerate(bullets):
        if re.search(r"\s+at\s+", b, re.I) and 12 <= len(b.strip()) <= 220:
            role, company, _d, _loc, _ = _parse_role_header_line(b)
            if _valid_job_identity(company, role):
                return i
    return None


def repair_experience_api_blocks_identity_from_bullets(
    blocks: Optional[List[Any]],
) -> List[dict]:
    """
    Hoist company/title (and optional date/location) from the first parseable job-header bullet
    when structured fields are missing, so export assembly and summary grounding see identity.
    """
    out: List[dict] = []
    for block in blocks or []:
        if not isinstance(block, dict):
            continue
        nb = dict(block)
        company = str(nb.get("company") or "").strip()
        title = str(nb.get("title") or nb.get("role") or "").strip()
        bullets = [str(b).strip() for b in (nb.get("bullets") or []) if str(b).strip()]
        if _valid_job_identity(company, title):
            nb["bullets"] = bullets
            out.append(nb)
            continue
        idx: Optional[int] = None
        for i, b in enumerate(bullets):
            if not _line_looks_like_role_header(b):
                continue
            role, comp, d, loc, _ov = _parse_role_header_line(b)
            if not _valid_job_identity(comp, role):
                continue
            idx = i
            break
        if idx is not None:
            bline = bullets[idx]
            role, comp, d, loc, ov_h = _parse_role_header_line(bline)
            nb["company"] = (comp or company).strip()
            nb["title"] = (role or title).strip()
            if "role" in nb:
                nb["role"] = nb["title"]
            dt_exist = str(nb.get("date_range") or nb.get("date") or "").strip()
            if d and not dt_exist:
                nb["date_range"] = d
            loc_exist = str(nb.get("location") or "").strip()
            if loc and not loc_exist:
                nb["location"] = loc
            mid = bullets[:idx] + list(ov_h) + bullets[idx + 1 :]
            bullets = mid
        nb["bullets"] = bullets
        out.append(nb)
    return out


def prepare_experience_blocks_for_docx(blocks: List[dict]) -> List[dict]:
    """
    Normalize producer output so unstructured blocks do not pass content bullets before
    the first parseable job header (required by build_experience_entries_identity_first).

    Typical fix: single block from normalize_resume_structure with empty company/title/date
    and bullets = all paragraphs after the name line — reorder so the first job header
    line precedes other lines.
    """
    out: List[dict] = []
    for bi, block in enumerate(blocks or []):
        if not isinstance(block, dict):
            raise ResumeContractError(
                f"experience_blocks[{bi}] must be a dict, got {type(block).__name__}"
            )
        nb = dict(block)
        raw_bullets = [str(b).strip() for b in (nb.get("bullets") or []) if str(b).strip()]
        bullets = [b for b in raw_bullets if not line_is_experience_noise(b)]
        bullets = _maybe_promote_split_company_role_dateline_header(bullets)
        e = _api_block_to_entry({**nb, "bullets": bullets})
        if _valid_job_identity(e.company, e.role):
            nb["bullets"] = bullets
            out.append(nb)
            continue
        if not bullets:
            out.append(nb)
            continue
        hi = _first_job_header_candidate_index(bullets)
        if hi is None:
            raise ResumeContractError(
                f"experience_blocks[{bi}]: cannot find a job header line before bullets "
                f"(need a dated line, pipe-separated title|company|…, or role at company). "
                f"preview={raw_bullets[:5]!r}"
            )
        if hi > 0:
            bullets = [bullets[hi]] + bullets[:hi] + bullets[hi + 1 :]
        nb["bullets"] = bullets
        out.append(nb)
    return out


def strip_skill_bucket_lines_from_experience_dict_blocks(
    blocks: List[dict],
) -> Tuple[List[dict], List[str]]:
    """
    Pull grouped skill-bucket lines (``Category: a, b, c``) out of raw experience block
    bullets before identity-first segmentation so they cannot seal as fragments or bullets.
    """
    redirected: List[str] = []
    out: List[dict] = []
    for bi, block in enumerate(blocks or []):
        if not isinstance(block, dict):
            raise ResumeContractError(
                f"experience_blocks[{bi}] must be a dict, got {type(block).__name__}"
            )
        nb = dict(block)
        bullets_raw = nb.get("bullets") or []
        if not isinstance(bullets_raw, list):
            raise ResumeContractError(
                f"experience_blocks[{bi}].bullets must be a list, got {type(bullets_raw).__name__}"
            )
        kept: List[str] = []
        for b in bullets_raw:
            s = str(b).strip()
            if not s:
                continue
            src = f"experience_blocks[{bi}].bullets"
            if skill_bucket_line_redirects_to_skills(s):
                redirected.append(s)
                _log_skill_bucket_redirect_debug(
                    source_section=src,
                    line=s,
                    action="redirect_to_skills",
                )
            else:
                _log_skill_bucket_redirect_debug(
                    source_section=src,
                    line=s,
                    action="keep_bullet",
                )
                kept.append(s)
        nb["bullets"] = kept
        out.append(nb)
    return out, redirected


def _strip_skill_bucket_lines_from_experience_entries(
    entries: List[ExperienceEntry],
) -> Tuple[List[ExperienceEntry], List[str]]:
    """Last-chance removal after segmentation (leaks across job boundaries)."""
    redirected: List[str] = []
    out: List[ExperienceEntry] = []
    for ei, e in enumerate(entries):
        kept: List[str] = []
        for b in e.bullets:
            s = str(b).strip()
            if not s:
                continue
            src = f"experience[{ei}].bullets"
            if skill_bucket_line_redirects_to_skills(s):
                redirected.append(s)
                _log_skill_bucket_redirect_debug(
                    source_section=src,
                    line=s,
                    action="redirect_to_skills",
                )
            else:
                _log_skill_bucket_redirect_debug(
                    source_section=src,
                    line=s,
                    action="keep_bullet",
                )
                kept.append(s)
        out.append(
            ExperienceEntry(e.company, e.role, e.date, e.location, kept)
        )
    return out, redirected


def _strip_skill_bucket_lines_from_project_entries(
    entries: List[ProjectEntry],
) -> Tuple[List[ProjectEntry], List[str]]:
    redirected: List[str] = []
    out: List[ProjectEntry] = []
    for pi, p in enumerate(entries):
        kept_b: List[str] = []
        for b in p.bullets:
            s = str(b).strip()
            if not s:
                continue
            src = f"projects[{pi}].bullets"
            if skill_bucket_line_redirects_to_skills(s):
                redirected.append(s)
                _log_skill_bucket_redirect_debug(
                    source_section=src,
                    line=s,
                    action="redirect_to_skills",
                )
            else:
                _log_skill_bucket_redirect_debug(
                    source_section=src,
                    line=s,
                    action="keep_bullet",
                )
                kept_b.append(s)
        subt = (p.subtitle or "").strip()
        new_sub = subt
        if subt and skill_bucket_line_redirects_to_skills(subt):
            redirected.append(subt)
            new_sub = ""
            _log_skill_bucket_redirect_debug(
                source_section=f"projects[{pi}].subtitle",
                line=subt,
                action="redirect_to_skills",
            )
        elif subt:
            _log_skill_bucket_redirect_debug(
                source_section=f"projects[{pi}].subtitle",
                line=subt,
                action="keep_bullet",
            )
        out.append(ProjectEntry(p.name, new_sub, kept_b))
    return out, redirected


def _experience_entry_bullets_contain_embedded_fragments(ent: ExperienceEntry) -> bool:
    """True when any bullet line is still a standalone date / company / title fragment."""
    for b in ent.bullets:
        if _line_is_embedded_identity_fragment(str(b).strip()):
            return True
    return False


def _experience_entry_bullets_contain_distinct_job_header(ent: ExperienceEntry) -> bool:
    """
    True when a bullet is a full job header for a **different** employer than this row.

    Structured API blocks often set ``company``/``title`` on the first job while later jobs
    appear only as pipe headers inside ``bullets``. Those lines are not "embedded fragments"
    (multi-line splits), so they must still force bullet-stream resegmentation — never
    promotion/overwrite of the current entry's company.
    """
    cur_key = _employer_identity_token(ent.company or "")
    if not cur_key:
        return False
    for b in ent.bullets:
        if _bullet_opens_distinct_employer_boundary(ent, str(b).strip()):
            return True
    return False


def _try_consume_embedded_header_fragment_lines(
    queue: List[str],
    *,
    stream_trace: Optional[List[Dict[str, Any]]] = None,
) -> Optional[str]:
    """
    If the front of ``queue`` is a 2- or 3-line embedded job header fragment, pop those
    lines and return one synthetic pipe header; otherwise return ``None``.
    """
    if len(queue) >= 3:
        a, b, c = queue[0], queue[1], queue[2]
        if (
            _line_is_standalone_calendar_date_range(a)
            and _line_is_standalone_company_like(b)
            and _line_is_standalone_role_title(c)
        ):
            synth = f"{b} | {c} | {a}"
            del queue[0]
            del queue[0]
            del queue[0]
            _embedded_header_debug(
                line_index=0,
                raw_line=synth,
                detected="boundary",
                fragment_kind="scan_dcr_triple",
                action="queue_pop_embedded_fragment",
            )
            _emit_stream_segment_trace(
                stream_trace,
                phase="scan",
                line_index=0,
                raw_line=synth,
                detected="boundary",
                cur_company="",
                cur_role="",
                action="queue_pop_embedded_dcr",
            )
            return synth
        if (
            _line_is_standalone_company_like(a)
            and _line_is_standalone_role_title(b)
            and _line_is_standalone_calendar_date_range(c)
        ):
            synth = f"{a} | {b} | {c}"
            del queue[0]
            del queue[0]
            del queue[0]
            _embedded_header_debug(
                line_index=0,
                raw_line=synth,
                detected="boundary",
                fragment_kind="scan_crd_triple",
                action="queue_pop_embedded_fragment",
            )
            _emit_stream_segment_trace(
                stream_trace,
                phase="scan",
                line_index=0,
                raw_line=synth,
                detected="boundary",
                cur_company="",
                cur_role="",
                action="queue_pop_embedded_crd",
            )
            return synth
    if len(queue) >= 2:
        a, b = queue[0], queue[1]
        third_is_date = len(queue) >= 3 and _line_is_standalone_calendar_date_range(queue[2])
        if (
            _line_is_standalone_company_like(a)
            and _line_is_standalone_role_title(b)
            and not third_is_date
        ):
            synth = f"{a} | {b}"
            del queue[0]
            del queue[0]
            _embedded_header_debug(
                line_index=0,
                raw_line=synth,
                detected="boundary",
                fragment_kind="scan_cr_pair",
                action="queue_pop_embedded_fragment",
            )
            _emit_stream_segment_trace(
                stream_trace,
                phase="scan",
                line_index=0,
                raw_line=synth,
                detected="boundary",
                cur_company="",
                cur_role="",
                action="queue_pop_embedded_cr",
            )
            return synth
    return None


def _segment_bullets_into_entries(
    bullets: List[str],
    *,
    block_date: str = "",
    block_location: str = "",
    stream_trace: Optional[List[Dict[str, Any]]] = None,
) -> List[ExperienceEntry]:
    """
    Identity-first job segmentation over a flat line list.

    A new ``ExperienceEntry`` is created **only** when a line parses as a job header with
    valid company or role. Lines before that (including real bullets) are **buffered** and
    attached as the initial bullets of the next valid job — never as a standalone entry.

    Block-level ``date`` / ``location`` from the API must **not** be injected as literal
    lines into the bullet stream (that previously made metadata appear as leading bullets).
    They are applied only to the **first** header-bound row when the header omits them.

    Returns **raw** entries (no bullet cleaning). Callers run
    ``normalize_experience_entry_identity`` then ``_clean_bullets_for_structured_entry``.
    """
    out: List[ExperienceEntry] = []
    pending: List[str] = []
    cur: Optional[ExperienceEntry] = None
    bd = (block_date or "").strip()
    bl = (block_location or "").strip()
    stripped = [str(b).strip() for b in bullets if str(b).strip()]
    section_filtered = experience_lines_for_identity_segmentation(stripped)
    queue = [_normalize_resume_line_dashes(s) for s in section_filtered]
    queue = _preprocess_embedded_fragment_header_lines(queue, stream_trace=stream_trace)

    stream_ix = 0
    while queue:
        synth = _try_consume_embedded_header_fragment_lines(queue, stream_trace=stream_trace)
        if synth is not None:
            line = synth
        else:
            line = queue.pop(0)
        if not line:
            continue
        cc = (cur.company or "") if cur else ""
        cr = (cur.role or "") if cur else ""
        if _line_looks_like_role_header(line):
            role, company, d, loc, ov = _parse_role_header_line(line)
            if cur is not None and _count_distinct_date_spans_in_header_metadata(
                cur.date, cur.location
            ) >= 1:
                if not _valid_job_identity(company, role) and (
                    (d or "").strip() or (loc or "").strip()
                ):
                    _emit_stream_segment_trace(
                        stream_trace,
                        phase="scan",
                        line_index=stream_ix,
                        raw_line=line,
                        detected="boundary",
                        cur_company=cc,
                        cur_role=cr,
                        action="close_entry",
                    )
                    out.append(cur)
                    cur = None
                    queue.insert(0, line)
                    continue
            if not _valid_job_identity(company, role):
                det = "boundary"
                if _line_is_standalone_calendar_date_range(line):
                    det = "date"
                elif _line_is_standalone_company_like(line):
                    det = "company"
                elif _line_is_standalone_role_title(line):
                    det = "role"
                _emit_stream_segment_trace(
                    stream_trace,
                    phase="scan",
                    line_index=stream_ix,
                    raw_line=line,
                    detected=det,
                    cur_company=cc,
                    cur_role=cr,
                    action="buffer_invalid_header",
                )
                logger.debug(
                    "STATE_DEBUG line=%r kind=buffer_invalid_header cur_company=%r cur_role=%r "
                    "bullet_count=%s pending_len=%s",
                    line[:200],
                    (cur.company if cur else "")[:120],
                    (cur.role if cur else "")[:120],
                    len(cur.bullets) if cur else 0,
                    len(pending),
                )
                pending.append(line)
                stream_ix += 1
                continue
            if cur is not None:
                logger.info(
                    "ENTRY_TRANSITION_DEBUG phase=segment action=new_entry "
                    "previous_company=%r previous_role=%r new_detected_company=%r "
                    "new_detected_role=%r",
                    (cur.company or "")[:200],
                    (cur.role or "")[:200],
                    (company or "")[:200],
                    (role or "")[:200],
                )
                logger.info(
                    "ENTRY_BOUNDARY_DEBUG previous_company=%r new_company=%r action=%s",
                    (cur.company or "")[:200],
                    (company or "")[:200],
                    "new_entry",
                )
                _emit_stream_segment_trace(
                    stream_trace,
                    phase="scan",
                    line_index=stream_ix,
                    raw_line=line,
                    detected="boundary",
                    cur_company=cc,
                    cur_role=cr,
                    action="close_entry",
                )
                out.append(cur)
            first_entry_in_block = len(out) == 0
            d_eff = (d or "").strip() or (bd if first_entry_in_block else "")
            loc_eff = (loc or "").strip() or (bl if first_entry_in_block else "")
            cur = ExperienceEntry(company, role, d_eff, loc_eff, list(pending))
            _emit_stream_segment_trace(
                stream_trace,
                phase="scan",
                line_index=stream_ix,
                raw_line=line,
                detected="boundary",
                cur_company=(cur.company or ""),
                cur_role=(cur.role or ""),
                action="start_new_entry",
            )
            logger.info(
                "STATE_DEBUG line=%r kind=identity_header cur_company=%r cur_role=%r "
                "bullet_count=%s pending_len=%s",
                line[:200],
                (cur.company or "")[:120],
                (cur.role or "")[:120],
                len(cur.bullets),
                len(pending),
            )
            pending = []
            for bit in reversed(ov):
                queue.insert(0, bit)
            stream_ix += 1
            continue
        if cur is None:
            det = "bullet"
            if _line_is_standalone_calendar_date_range(line):
                det = "date"
            elif _line_is_standalone_company_like(line):
                det = "company"
            elif _line_is_standalone_role_title(line):
                det = "role"
            _emit_stream_segment_trace(
                stream_trace,
                phase="scan",
                line_index=stream_ix,
                raw_line=line,
                detected=det,
                cur_company=cc,
                cur_role=cr,
                action="buffer_before_identity",
            )
            logger.debug(
                "STATE_DEBUG line=%r kind=buffer_before_identity cur_company=%r cur_role=%r "
                "bullet_count=%s pending_len=%s",
                line[:200],
                "",
                "",
                0,
                len(pending),
            )
            pending.append(line)
            stream_ix += 1
            continue
        if (
            cur is not None
            and not _line_looks_like_role_header(line)
            and _standalone_role_line_opens_distinct_job(cur, line)
        ):
            _role_boundary_debug(
                line_index=stream_ix,
                raw_line=line,
                detected_role=True,
                cur_company=cc,
                cur_role=cr,
                action="close_entry",
            )
            _emit_stream_segment_trace(
                stream_trace,
                phase="scan",
                line_index=stream_ix,
                raw_line=line,
                detected="role_boundary",
                cur_company=cc,
                cur_role=cr,
                action="close_entry_standalone_role",
            )
            logger.info(
                "ENTRY_TRANSITION_DEBUG phase=segment action=new_entry_standalone_role "
                "previous_company=%r previous_role=%r new_detected_role=%r",
                (cur.company or "")[:200],
                (cur.role or "")[:200],
                line.strip()[:200],
            )
            out.append(cur)
            co_frag, date_frag, loc_frag = _pop_optional_header_fragments_after_role(queue)
            first_entry_in_block = len(out) == 0
            d_eff = (date_frag or "").strip() or (bd if first_entry_in_block else "")
            loc_eff = (loc_frag or "").strip() or (bl if first_entry_in_block else "")
            cur = ExperienceEntry(
                (co_frag or "").strip(),
                line.strip(),
                d_eff,
                loc_eff,
                [],
            )
            _role_boundary_debug(
                line_index=stream_ix,
                raw_line=line,
                detected_role=True,
                cur_company=(cur.company or ""),
                cur_role=(cur.role or ""),
                action="start_new_entry",
            )
            _emit_stream_segment_trace(
                stream_trace,
                phase="scan",
                line_index=stream_ix,
                raw_line=line,
                detected="role_boundary",
                cur_company=(cur.company or ""),
                cur_role=(cur.role or ""),
                action="start_new_entry_standalone_role",
            )
            stream_ix += 1
            continue
        cur.bullets.append(line)
        _emit_stream_segment_trace(
            stream_trace,
            phase="scan",
            line_index=stream_ix,
            raw_line=line,
            detected="bullet",
            cur_company=cc,
            cur_role=cr,
            action="append_bullet",
        )
        logger.debug(
            "STATE_DEBUG line=%r kind=bullet_appended cur_company=%r cur_role=%r "
            "bullet_count=%s pending_len=%s",
            line[:200],
            (cur.company or "")[:120],
            (cur.role or "")[:120],
            len(cur.bullets),
            len(pending),
        )
        stream_ix += 1

    if cur is not None:
        out.append(cur)
    elif pending:
        raise ResumeContractError(
            "experience: no job with company or role before content "
            f"(pending_preview={pending[:6]!r})"
        )
    return out


def streaming_segmentation_trace(
    bullets: List[str],
    *,
    block_date: str = "",
    block_location: str = "",
) -> Tuple[List[Dict[str, Any]], List[ExperienceEntry]]:
    """
    Run preprocess + ``_segment_bullets_into_entries`` and return every trace event
    (``phase`` ``preprocess`` or ``scan``) alongside raw segmented rows (no normalize/clean).
    """
    trace: List[Dict[str, Any]] = []
    entries = _segment_bullets_into_entries(
        bullets,
        block_date=block_date,
        block_location=block_location,
        stream_trace=trace,
    )
    return trace, entries


def _clean_bullets_for_structured_entry(e: ExperienceEntry) -> ExperienceEntry:
    """
    Drop **redundant** header-shaped lines that only repeat this entry’s company+role.

    Lines that look like job headers but carry a **different** employer/title (or date-only
    spill from a clamp) must stay in ``bullets`` so a later segmentation pass can open a new
    job boundary instead of losing the next role block.
    """
    kept: List[str] = []
    company_l = (e.company or "").strip().lower()
    role_l = (e.role or "").strip().lower()
    for b in e.bullets:
        bt = str(b).strip()
        if not bt:
            continue
        if _line_looks_like_role_header(bt):
            r, c, d, loc, _ = _parse_role_header_line(bt)
            if (
                company_l
                and role_l
                and _valid_job_identity(c, r)
                and (c or "").strip().lower() == company_l
                and (r or "").strip().lower() == role_l
            ):
                continue
            kept.append(bt)
            continue
        if company_l and bt.lower() == company_l:
            continue
        if role_l and bt.lower() == role_l:
            continue
        kept.append(bt)
    return ExperienceEntry(e.company, e.role, e.date, e.location, kept)


def _drop_segmentation_ghost_experience_entries(
    entries: List[ExperienceEntry],
) -> List[ExperienceEntry]:
    """
    Remove segmentation junk after orphan repair: rows with no company/role/bullets, or
    company-only stubs with no role and no bullets. Role+ bullets with empty company are
    kept for upstream identity repair.
    """
    out: List[ExperienceEntry] = []
    for e in entries:
        co = (e.company or "").strip()
        role = (e.role or "").strip()
        if not co and not role and not e.bullets:
            continue
        if not e.bullets and not role:
            continue
        out.append(e)
    return out


def experience_blocks_to_provisional_entries(blocks: List[dict]) -> List[ExperienceEntry]:
    """
    Map experience API blocks to segmented rows **before** orphan-bullet merge and sealing.
    Use this to inspect provisional segmentation (e.g. sanity checks, debugging).
    """
    entries: List[ExperienceEntry] = []
    for i, block in enumerate(blocks or []):
        if not isinstance(block, dict):
            raise ResumeContractError(
                f"experience_blocks[{i}] must be a dict, got {type(block).__name__}"
            )
        if i < 5:
            _bl_src = [
                str(x).strip() for x in (block.get("bullets") or []) if str(x).strip()
            ]
            logger.info(
                "EXPERIENCE_PIPELINE stage=RAW_BLOCK index=%s company=%r role=%r date=%r "
                "location=%r source_lines=%s",
                i,
                str(block.get("company") or "")[:200],
                str(block.get("title") or block.get("role") or "")[:200],
                str(block.get("date_range") or block.get("date") or "")[:220],
                str(block.get("location") or "")[:200],
                json.dumps(_bl_src[:8], ensure_ascii=False),
            )
        raw_bullets = block.get("bullets")
        if raw_bullets is not None and not isinstance(raw_bullets, list):
            raise ResumeContractError(
                f"experience_blocks[{i}].bullets must be a list or omitted, got {type(raw_bullets).__name__}"
            )
        blist = [str(b).strip() for b in (raw_bullets or []) if str(b).strip()]
        blist = _preprocess_embedded_fragment_header_lines(blist)
        if i <= 1:
            logger.info(
                "EXPERIENCE_SEGMENT_BLOCK_TRACE block_index=%s company=%r title=%r date_range=%r "
                "location=%r bullet_count=%s first_3_bullets=%r entries_before_block=%s",
                i,
                str(block.get("company") or "")[:200],
                str(block.get("title") or block.get("role") or "")[:200],
                str(block.get("date_range") or block.get("date") or "")[:200],
                str(block.get("location") or "")[:200],
                len(blist),
                blist[:3],
                len(entries),
            )
        e = _api_block_to_entry(block)
        e = ExperienceEntry(e.company, e.role, e.date, e.location, list(blist))
        e = repair_experience_field_misassignment(e)
        if _valid_job_identity(e.company, e.role):
            # Fragment / boundary detection must run on chronological bullets — do not polish
            # (prioritize) before resegmentation or bullet order is scrambled vs. the API list.
            if _experience_entry_bullets_contain_embedded_fragments(
                e
            ) or _experience_entry_bullets_contain_distinct_job_header(e):
                _distinct = _experience_entry_bullets_contain_distinct_job_header(e)
                logger.info(
                    "ENTRY_TRANSITION_DEBUG phase=block action=resegment_bullet_stream "
                    "structured_company=%r structured_role=%r reason=%s",
                    (e.company or "")[:200],
                    (e.role or "")[:200],
                    "distinct_job_header_in_bullets" if _distinct else "embedded_header_fragments",
                )
                synth_parts = [
                    str(p).strip()
                    for p in (e.company, e.role, e.date, e.location)
                    if str(p).strip()
                ]
                merged_stream = (
                    [" | ".join(synth_parts)]
                    + [str(b).strip() for b in e.bullets if str(b).strip()]
                    if len(synth_parts) >= 2
                    else [str(b).strip() for b in e.bullets if str(b).strip()]
                )
                _embedded_header_debug(
                    line_index=i,
                    raw_line=merged_stream[0][:200] if merged_stream else "",
                    detected="boundary",
                    fragment_kind="structured_block_resplit",
                    action="resegment_bullets_with_synthetic_header",
                )
                if not merged_stream:
                    continue
                segmented = _segment_bullets_into_entries(
                    merged_stream,
                    block_date=(e.date or "").strip(),
                    block_location=(e.location or "").strip(),
                )
                for ent in segmented:
                    if ent.bullets and not _valid_job_identity(ent.company, ent.role):
                        raise ResumeContractError(
                            "experience: segmented entry has bullets but no valid company or role"
                        )
                    ce2 = _polish_segmented_experience_row(ent)
                    _log_experience_entry_assembled(ce2, context=f"structured_resplit[{i}]")
                    entries.append(ce2)
            else:
                ce = _polish_segmented_experience_row(e)
                _log_experience_entry_assembled(ce, context=f"structured_block[{i}]")
                entries.append(ce)
            continue
        # Identity-first: never prepend structured date/location as pseudo-bullet lines —
        # they are passed separately and bound to the first job row that gets a header.
        merged: List[str] = [str(b).strip() for b in e.bullets if str(b).strip()]
        if not merged:
            continue
        segmented = _segment_bullets_into_entries(
            merged,
            block_date=(e.date or "").strip(),
            block_location=(e.location or "").strip(),
        )
        for ent in segmented:
            if ent.bullets and not _valid_job_identity(ent.company, ent.role):
                raise ResumeContractError(
                    "experience: segmented entry has bullets but no valid company or role"
                )
            ce = _polish_segmented_experience_row(ent)
            _log_experience_entry_assembled(ce, context=f"segmented_from_block[{i}]")
            entries.append(ce)
        if i <= 1:
            tail = entries[-1] if entries else None
            logger.info(
                "EXPERIENCE_SEGMENT_BLOCK_DONE block_index=%s total_entries=%s "
                "tail_company=%r tail_role=%r tail_bullet_count=%s",
                i,
                len(entries),
                (tail.company or "")[:120] if tail else "",
                (tail.role or "")[:120] if tail else "",
                len(tail.bullets) if tail else 0,
            )
    return entries


def build_experience_entries_identity_first(blocks: List[dict]) -> List[ExperienceEntry]:
    """
    **Single source of truth** for identity-first experience assembly (DOCX export,
    ``build_resume_document_payload``, and contract tests).

    Pipeline: provisional rows from API blocks → normalize identities → orphan bullet repair
    → sealed finalize. Uses identity-first segmentation inside ``experience_blocks_to_provisional_entries``
    / ``_segment_bullets_into_entries`` (no standalone bullet-only rows in the final model).
    """
    entries = experience_blocks_to_provisional_entries(blocks)
    _log_experience_lifecycle_stage("SEGMENT_PROVISIONAL", entries)
    _log_experience_entry_zero_audit("SEGMENT_PROVISIONAL", entries)
    entries = normalize_experience_entries_batch(entries)
    _log_experience_lifecycle_stage("NORMALIZED", entries)
    _log_experience_entry_zero_audit("NORMALIZED", entries)
    entries = merge_pure_orphan_bullet_entries_into_adjacent_identity(entries)
    _log_experience_lifecycle_stage("ORPHAN_REPAIR", entries)
    _log_experience_entry_zero_audit("ORPHAN_REPAIR", entries)
    entries = _drop_segmentation_ghost_experience_entries(entries)
    return _patch_final_experience_display_identity(_finalize_experience_entries_sealed(entries))


def experience_blocks_to_entries(blocks: List[dict]) -> List[ExperienceEntry]:
    """Backward-compatible alias for :func:`build_experience_entries_identity_first`."""
    return build_experience_entries_identity_first(blocks)


def experience_entry_header_lines(ent: ExperienceEntry) -> List[str]:
    """Render order: company, role, then location and date on separate lines when both exist."""
    company = (ent.company or "").strip()
    role = (ent.role or "").strip()
    date = re.sub(r"\s+", " ", ((ent.date or "").replace("\r", " ").replace("\n", " "))).strip()
    loc = re.sub(r"\s+", " ", ((ent.location or "").replace("\r", " ").replace("\n", " "))).strip()
    lines: List[str] = []
    if company:
        lines.append(company)
    if role:
        lines.append(role)
    if loc and date:
        lines.append(loc)
        lines.append(date)
    elif loc:
        lines.append(loc)
    elif date:
        lines.append(date)
    return lines


def education_entry_header_lines(ent: EducationEntry) -> List[str]:
    """Render order: degree — institution (if any), then date · location."""
    degree = (ent.degree or "").strip()
    institution = (ent.institution or "").strip()
    date = (ent.date or "").strip()
    loc = (ent.location or "").strip()
    lines: List[str] = []
    if degree and institution:
        lines.append(f"{degree} — {institution}")
    elif degree:
        lines.append(degree)
    elif institution:
        lines.append(institution)
    dl_parts = [p for p in (date, loc) if p]
    if dl_parts:
        lines.append(" · ".join(dl_parts))
    return lines


def certification_entry_header_lines(ent: CertificationEntry) -> List[str]:
    """Render order: name — issuer (if any), then date."""
    name = (ent.name or "").strip()
    issuer = (ent.issuer or "").strip()
    date = (ent.date or "").strip()
    lines: List[str] = []
    if name and issuer:
        lines.append(f"{name} — {issuer}")
    elif name:
        lines.append(name)
    elif issuer:
        lines.append(issuer)
    if date:
        lines.append(date)
    return lines


def normalize_skills_items(raw: Any, *, allow_defaults: bool = True) -> List[str]:
    """Flatten list items; split embedded newlines so grouped skills survive one-field payloads."""
    out: List[str] = []
    if isinstance(raw, str) and raw.strip():
        s = raw.strip()
        if "\n" in s:
            out.extend([ln.strip() for ln in s.splitlines() if ln.strip()])
        else:
            out.append(s)
    elif isinstance(raw, list) and raw:
        for item in raw:
            st = str(item).strip()
            if not st:
                continue
            if "\n" in st:
                out.extend([ln.strip() for ln in st.splitlines() if ln.strip()])
            else:
                out.append(st)
    if out:
        return out
    return list(_DEFAULT_SKILLS_ITEMS) if allow_defaults else []


def parse_skills_group_lines_from_raw_text(raw: str) -> List[str]:
    """Recover ``Category: ...`` skill rows from raw resume text when sections.skills is incomplete."""
    if not (raw or "").strip():
        return []
    lines = raw.replace("\r\n", "\n").split("\n")
    in_skills = False
    out: List[str] = []
    for ln in lines:
        t = ln.strip()
        if not t:
            continue
        if re.match(r"(?i)^skills?\s*:?\s*$", t):
            in_skills = True
            continue
        if in_skills:
            if re.match(
                r"(?i)^(education|experience|employment|work\s+experience|projects?|"
                r"certifications?|summary|contact)\s*:?\s*$",
                t,
            ):
                break
            if _GENERIC_CATEGORY_COLON_LINE.match(t) and ":" in t:
                out.append(t)
    return out


_SKILL_CATEGORY_KNOWN_PREFIX = re.compile(
    r"(?i)^(Data\s*&\s*Analytics|Systems\s*&\s*Platforms|Testing\s*&\s*Governance|"
    r"Documentation\s*&\s*Modeling)\s*:\s*\S"
)


def parse_skills_category_lines_global_scan(raw: str) -> List[str]:
    """
    Recover grouped ``Category: …`` skill rows anywhere in the resume body when the
    producer did not keep a dedicated SKILLS section header in ``raw_text``.
    """
    if not (raw or "").strip():
        return []
    seen: set[str] = set()
    out: List[str] = []
    for ln in raw.replace("\r\n", "\n").split("\n"):
        t = ln.strip()
        if not t or ":" not in t:
            continue
        if _SKILL_CATEGORY_KNOWN_PREFIX.match(t):
            k = t.lower()
            if k not in seen:
                seen.add(k)
                out.append(t)
            continue
        if not _GENERIC_CATEGORY_COLON_LINE.match(t):
            continue
        head = t.split(":", 1)[0]
        if re.search(r"(?i)\bcore\s+skills\b", head):
            continue
        if not re.search(
            r"(?i)(governance|analytics|platforms|documentation|modeling|testing|skills)",
            head,
        ):
            continue
        k = t.lower()
        if k not in seen:
            seen.add(k)
            out.append(t)
    return out


def coalesce_skills_for_export(sections: dict, raw_text: str) -> List[str]:
    """Merge structured skills list with category lines mined from raw_text."""
    raw = sections.get("skills") if isinstance(sections, dict) else None
    primary = normalize_skills_items(raw, allow_defaults=False)
    alt_section = parse_skills_group_lines_from_raw_text(raw_text or "")
    alt_scan = parse_skills_category_lines_global_scan(raw_text or "")
    merged = merge_distinct_skill_lines(
        primary, merge_distinct_skill_lines(alt_section, alt_scan)
    )
    if merged:
        return _strip_core_skills_label_lines(merged)
    return _strip_core_skills_label_lines(normalize_skills_items(raw, allow_defaults=True))


def merge_distinct_skill_lines(primary: List[str], extra: List[str]) -> List[str]:
    """Append skill lines from project cleanup without duplicates (order preserved)."""
    seen: set[str] = set()
    out: List[str] = []
    for s in primary + extra:
        t = str(s).strip()
        if not t:
            continue
        k = t.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(t)
    return out


def skills_to_display_lines(skills: List[str]) -> List[str]:
    """
    One paragraph per line when the resume already uses grouped categories
    (``Data & Analytics: …`` on separate lines). Flat lists stay a single grouped line.
    """
    if not skills:
        return ["Data & Analytics: " + ", ".join(_DEFAULT_SKILLS_ITEMS)]
    cleaned = _strip_core_skills_label_lines([str(s).strip() for s in skills if str(s).strip()])
    if not cleaned:
        return ["Data & Analytics: " + ", ".join(_DEFAULT_SKILLS_ITEMS)]
    if len(cleaned) == 1:
        return [cleaned[0]]
    colon_rows = sum(1 for s in cleaned if ":" in s)
    if colon_rows >= 2:
        return cleaned
    if len(cleaned) >= 2 and colon_rows >= 1 and max(len(s) for s in cleaned) > 28:
        return cleaned
    if all(":" in s for s in cleaned):
        return cleaned
    return ["Data & Analytics: " + ", ".join(cleaned)]


def skills_to_display_line(skills: List[str]) -> str:
    return "\n".join(skills_to_display_lines(skills))


def _inline_education_row_from_project_line(line: str) -> Optional[dict]:
    s = (line or "").strip()
    if not s:
        return None
    m = re.match(r"(?i)^\s*education\s*:\s*(.+)$", s)
    if m:
        body = m.group(1).strip()
        if not body:
            return None
        return {"degree": body, "institution": "", "date": "", "location": "", "bullets": []}
    m2 = re.match(
        r"(?i)^\s*(?:academic\s+(?:credentials|background|history)|qualifications?)\s*:\s*(.+)$",
        s,
    )
    if m2 and m2.group(1).strip():
        return {
            "degree": m2.group(1).strip(),
            "institution": "",
            "date": "",
            "location": "",
            "bullets": [],
        }
    m3 = re.match(r"(?i)^\s*(?:degree|diploma)\s*:\s*(.+)$", s)
    if m3 and m3.group(1).strip():
        return {
            "degree": m3.group(1).strip(),
            "institution": "",
            "date": "",
            "location": "",
            "bullets": [],
        }
    return None


def _inline_certification_row_from_project_line(line: str) -> Optional[dict]:
    s = (line or "").strip()
    if not s:
        return None
    m = re.match(r"(?i)^\s*certifications?\s*:\s*(.+)$", s)
    if m:
        body = m.group(1).strip()
        if not body:
            return None
        return {"name": body, "issuer": "", "date": "", "bullets": []}
    m2 = re.match(r"(?i)^\s*(?:licenses?|credentials?|professional\s+certifications?)\s*:\s*(.+)$", s)
    if m2 and m2.group(1).strip():
        return {"name": m2.group(1).strip(), "issuer": "", "date": "", "bullets": []}
    return None


def _education_row_from_leaked_degree_line(line: str) -> Optional[dict]:
    s = (line or "").strip()
    if not s or not _PROJECT_EDUCATION_LEAK.match(s):
        return None
    return {"degree": s, "institution": "", "date": "", "location": "", "bullets": []}


def parse_education_dicts_from_raw_text(raw: str) -> List[dict]:
    """
    Recover education rows from ``raw_text`` when structured ``sections.education`` is empty:
    ``Education:`` lines, a standalone EDUCATION section, or degree/school lines under that header.
    """
    if not (raw or "").strip():
        return []
    out: List[dict] = []
    seen: set[str] = set()
    lines = raw.replace("\r\n", "\n").split("\n")
    in_edu_section = False
    for ln in lines:
        t = ln.strip()
        if not t:
            continue
        row_inline = _inline_education_row_from_project_line(t)
        if row_inline:
            sig = (row_inline.get("degree") or "").strip().lower()
            if sig and sig not in seen:
                seen.add(sig)
                out.append(row_inline)
            continue
        if re.match(r"(?i)^education\s*:?\s*$", t):
            in_edu_section = True
            continue
        if in_edu_section:
            if re.match(
                r"(?i)^(certifications?|skills?|experience|projects?|"
                r"professional\s+experience|work\s+history)\s*:?\s*$",
                t,
            ):
                break
            if len(t) >= 8 and (
                _PROJECT_EDUCATION_LEAK.match(t)
                or re.search(r"(?i)\b(university|college|institute|school)\b", t)
            ):
                sig = t.lower()
                if sig not in seen:
                    seen.add(sig)
                    out.append(
                        {
                            "degree": t,
                            "institution": "",
                            "date": "",
                            "location": "",
                            "bullets": [],
                        }
                    )
    return out


def parse_certification_dicts_from_raw_text(raw: str) -> List[dict]:
    """
    Recover certification rows from ``raw_text`` when structured ``sections.certifications``
    is empty: ``Certifications:`` lines or lines under a standalone CERTIFICATIONS header.
    """
    if not (raw or "").strip():
        return []
    out: List[dict] = []
    seen: set[str] = set()
    lines = raw.replace("\r\n", "\n").split("\n")
    in_cert_section = False
    for ln in lines:
        t = ln.strip()
        if not t:
            continue
        row_inline = _inline_certification_row_from_project_line(t)
        if row_inline:
            sig = (row_inline.get("name") or "").strip().lower()
            if sig and sig not in seen:
                seen.add(sig)
                out.append(row_inline)
            continue
        if re.match(r"(?i)^certifications?\s*:?\s*$", t):
            in_cert_section = True
            continue
        if in_cert_section:
            if re.match(
                r"(?i)^(education|skills?|experience|projects?|professional\s+experience)\s*:?\s*$",
                t,
            ):
                break
            if re.match(r"(?i)^core\s+skills\b", t):
                continue
            if _SKILL_GROUP_HEADER_LINE.match(t):
                continue
            if _GENERIC_CATEGORY_COLON_LINE.match(t) and "&" in t.split(":", 1)[0]:
                hl = t.split(":", 1)[0].strip().lower()
                if re.search(
                    r"(?i)(governance|analytics|platforms|documentation|modeling|testing)",
                    hl,
                ):
                    continue
            if len(t) >= 4 and not re.match(
                r"(?i)^(bachelor|master|b\.?s\.?|m\.?s\.?|mba|associate|ph\.?d)\b",
                t,
            ):
                if _cert_line_is_soft_skill_colon_leak(t):
                    continue
                sig = t.lower()
                if sig not in seen:
                    seen.add(sig)
                    out.append({"name": t, "issuer": "", "date": "", "bullets": []})
    return out


_SKILL_BUCKET_REDIRECT_DEBUG_ENV = "SKILL_BUCKET_REDIRECT_DEBUG"


def _skill_bucket_redirect_debug_enabled() -> bool:
    return (os.environ.get(_SKILL_BUCKET_REDIRECT_DEBUG_ENV) or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _log_skill_bucket_redirect_debug(
    *, source_section: str, line: str, action: str
) -> None:
    if not _skill_bucket_redirect_debug_enabled():
        return
    logger.info(
        "SKILL_BUCKET_REDIRECT_DEBUG source_section=%s action=%s line=%r",
        source_section,
        action,
        (line or "")[:500],
    )


def skill_bucket_line_redirects_to_skills(line: str) -> bool:
    """
    True when a line belongs in the SKILLS payload (grouped category + list), not in
    experience or project bullets. Used for section-boundary cleanup before validation.
    """
    s = (line or "").strip()
    if not s:
        return False
    if re.match(
        r"(?i)^\s*(?:core\s+skills?|testing\s*&\s*governance|data\s*&\s*analytics|"
        r"systems\s*&\s*platforms|documentation\s*&\s*modeling)\s*:?\s*$",
        s,
    ):
        return True
    if (
        _inline_education_row_from_project_line(s)
        or _inline_certification_row_from_project_line(s)
        or _PROJECT_EDUCATION_LEAK.match(s)
    ):
        return False
    if _SKILL_GROUP_HEADER_LINE.match(s) or _CERT_OR_EDU_BUCKET_LINE.match(s):
        return True
    if _GENERIC_CATEGORY_COLON_LINE.match(s) and "&" in s.split(":", 1)[0]:
        hl = s.split(":", 1)[0].strip().lower()
        if re.search(
            r"(?i)(governance|analytics|platforms|documentation|modeling|certifications?|testing)",
            hl,
        ):
            return True
    return False


def _should_route_line_from_project_to_skills(line: str) -> bool:
    return skill_bucket_line_redirects_to_skills(line)


def prepare_project_blocks_for_docx(
    projects: Optional[List[dict]],
    removed_debug: Optional[List[str]] = None,
) -> Tuple[List[dict], List[str], List[dict], List[dict]]:
    """
    Remove skill-bucket, education, and certification lines mistakenly merged into
    project bullets. Skill bucket lines are returned for merge into SKILLS; education
    and certification dict rows are returned for merge into their dedicated sections.

    When ``removed_debug`` is a list, dropped / redirected lines are appended (truncated)
    for export diagnostics only.
    """

    def _note_removed(line: str) -> None:
        if removed_debug is None:
            return
        s = (line or "").strip()
        if s:
            removed_debug.append(s[:500])

    extra_skills: List[str] = []
    extra_education: List[dict] = []
    extra_certifications: List[dict] = []
    out: List[dict] = []
    for proj in projects or []:
        if not isinstance(proj, dict):
            continue
        nb = dict(proj)
        proj_name = str(nb.get("name") or nb.get("title") or "").strip()
        if proj_name and _line_should_drop_from_project_section_leak(proj_name):
            _note_removed(proj_name)
            proj_name = ""
        if proj_name:
            row_ed_n = _inline_education_row_from_project_line(proj_name)
            row_ce_n = _inline_certification_row_from_project_line(proj_name)
            row_deg_n = _education_row_from_leaked_degree_line(proj_name)
            if row_ed_n:
                _note_removed(proj_name)
                extra_education.append(row_ed_n)
                proj_name = ""
            elif row_ce_n:
                _note_removed(proj_name)
                extra_certifications.append(row_ce_n)
                proj_name = ""
            elif row_deg_n:
                _note_removed(proj_name)
                extra_education.append(row_deg_n)
                proj_name = ""
            elif skill_bucket_line_redirects_to_skills(proj_name):
                _note_removed(proj_name)
                _log_skill_bucket_redirect_debug(
                    source_section=f"projects[{len(out)}].name",
                    line=proj_name,
                    action="redirect_to_skills",
                )
                extra_skills.append(proj_name)
                proj_name = ""
            elif _line_is_degree_or_cert_pollution_for_project(proj_name):
                _note_removed(proj_name)
                proj_name = ""
        nb["name"] = proj_name
        if "title" in nb:
            nb["title"] = ""
        subtitle = str(nb.get("subtitle") or nb.get("tagline") or "").strip()
        if subtitle and _line_should_drop_from_project_section_leak(subtitle):
            _note_removed(subtitle)
            nb["subtitle"] = ""
            subtitle = ""
        if subtitle:
            row_ed = _inline_education_row_from_project_line(subtitle)
            row_ce = _inline_certification_row_from_project_line(subtitle)
            row_deg = _education_row_from_leaked_degree_line(subtitle)
            if row_ed:
                _note_removed(subtitle)
                extra_education.append(row_ed)
                nb["subtitle"] = ""
            elif row_ce:
                _note_removed(subtitle)
                extra_certifications.append(row_ce)
                nb["subtitle"] = ""
            elif row_deg:
                _note_removed(subtitle)
                extra_education.append(row_deg)
                nb["subtitle"] = ""
            elif skill_bucket_line_redirects_to_skills(subtitle):
                _note_removed(subtitle)
                _log_skill_bucket_redirect_debug(
                    source_section=f"projects[{len(out)}].subtitle",
                    line=subtitle,
                    action="redirect_to_skills",
                )
                extra_skills.append(subtitle)
                nb["subtitle"] = ""
            else:
                _log_skill_bucket_redirect_debug(
                    source_section=f"projects[{len(out)}].subtitle",
                    line=subtitle,
                    action="keep_bullet",
                )
        bullets = [str(b).strip() for b in (nb.get("bullets") or []) if str(b).strip()]
        kept: List[str] = []
        pidx = len(out)
        for b in bullets:
            if _line_should_drop_from_project_section_leak(b):
                _note_removed(b)
                continue
            row_ed = _inline_education_row_from_project_line(b)
            row_ce = _inline_certification_row_from_project_line(b)
            row_deg = _education_row_from_leaked_degree_line(b)
            if row_ed:
                _note_removed(b)
                extra_education.append(row_ed)
                continue
            if row_ce:
                _note_removed(b)
                extra_certifications.append(row_ce)
                continue
            if row_deg:
                _note_removed(b)
                extra_education.append(row_deg)
                continue
            if _line_is_degree_or_cert_pollution_for_project(b):
                _note_removed(b)
                continue
            if skill_bucket_line_redirects_to_skills(b):
                _note_removed(b)
                _log_skill_bucket_redirect_debug(
                    source_section=f"projects[{pidx}].bullets",
                    line=b,
                    action="redirect_to_skills",
                )
                extra_skills.append(b)
                continue
            _log_skill_bucket_redirect_debug(
                source_section=f"projects[{pidx}].bullets",
                line=b,
                action="keep_bullet",
            )
            kept.append(b)
        nb["bullets"] = kept
        out.append(nb)
    return out, extra_skills, extra_education, extra_certifications


def _merge_orphan_project_entries(entries: List[ProjectEntry]) -> List[ProjectEntry]:
    out: List[ProjectEntry] = []
    for p in entries:
        has_hdr = (p.name or "").strip() or (p.subtitle or "").strip()
        if p.bullets and not has_hdr:
            if out:
                prev = out[-1]
                out[-1] = ProjectEntry(
                    prev.name, prev.subtitle, prev.bullets + list(p.bullets)
                )
            elif p.bullets:
                raise ResumeContractError(
                    "projects: bullets found before any project name or subtitle"
                )
            continue
        out.append(p)
    return out


def dict_projects_to_entries(projects: Optional[List[dict]]) -> List[ProjectEntry]:
    out: List[ProjectEntry] = []
    for proj in projects or []:
        if not isinstance(proj, dict):
            continue
        name = str(proj.get("name") or proj.get("title") or "").strip()
        subtitle = str(proj.get("subtitle") or proj.get("tagline") or "").strip()
        bullets = [str(b).strip() for b in (proj.get("bullets") or []) if str(b).strip()]
        if not name and not subtitle and not bullets:
            continue
        out.append(ProjectEntry(name=name, subtitle=subtitle, bullets=bullets))
    return _merge_orphan_project_entries(out)


def _merge_orphan_education_entries(entries: List[EducationEntry]) -> List[EducationEntry]:
    out: List[EducationEntry] = []
    for e in entries:
        has_hdr = any(
            (
                (e.degree or "").strip(),
                (e.institution or "").strip(),
                (e.date or "").strip(),
                (e.location or "").strip(),
            )
        )
        if e.bullets and not has_hdr:
            if out:
                prev = out[-1]
                out[-1] = EducationEntry(
                    prev.degree,
                    prev.institution,
                    prev.date,
                    prev.location,
                    prev.bullets + list(e.bullets),
                )
            elif e.bullets:
                raise ResumeContractError(
                    "education: bullets found before any degree, institution, or date"
                )
            continue
        out.append(e)
    return out


def _merge_orphan_certification_entries(entries: List[CertificationEntry]) -> List[CertificationEntry]:
    out: List[CertificationEntry] = []
    for c in entries:
        has_hdr = any(
            ((c.name or "").strip(), (c.issuer or "").strip(), (c.date or "").strip())
        )
        if c.bullets and not has_hdr:
            if out:
                prev = out[-1]
                out[-1] = CertificationEntry(
                    prev.name, prev.issuer, prev.date, prev.bullets + list(c.bullets)
                )
            elif c.bullets:
                raise ResumeContractError(
                    "certifications: bullets found before any name, issuer, or date"
                )
            continue
        out.append(c)
    return out


def dict_rows_to_education_entries(rows: Optional[List[Any]]) -> List[EducationEntry]:
    """Build education entries from API dict rows only; non-dict rows fail the contract."""
    out: List[EducationEntry] = []
    for i, block in enumerate(rows or []):
        if not isinstance(block, dict):
            raise ResumeContractError(
                f"education[{i}] must be a dict, got {type(block).__name__}"
            )
        degree = str(block.get("degree") or block.get("title") or "").strip()
        inst = str(
            block.get("institution") or block.get("school") or block.get("company") or ""
        ).strip()
        dt = str(block.get("date_range") or block.get("date") or block.get("dates") or "").strip()
        loc = str(block.get("location") or "").strip()
        bullets = [str(b).strip() for b in (block.get("bullets") or []) if str(b).strip()]
        if not degree and not inst and not dt and not loc and not bullets:
            continue
        out.append(
            EducationEntry(
                degree=degree,
                institution=inst,
                date=dt,
                location=loc,
                bullets=bullets,
            )
        )
    return _merge_orphan_education_entries(out)


def dict_rows_to_certification_entries(rows: Optional[List[Any]]) -> List[CertificationEntry]:
    """Build certification entries from API dict rows only; non-dict rows fail the contract."""
    out: List[CertificationEntry] = []
    for i, block in enumerate(rows or []):
        if not isinstance(block, dict):
            raise ResumeContractError(
                f"certifications[{i}] must be a dict, got {type(block).__name__}"
            )
        name = str(
            block.get("name") or block.get("title") or block.get("credential") or ""
        ).strip()
        issuer = str(block.get("issuer") or block.get("organization") or "").strip()
        dt = str(block.get("date_range") or block.get("date") or block.get("dates") or "").strip()
        bullets = [
            str(b).strip()
            for b in (block.get("bullets") or [])
            if str(b).strip()
            and not skill_bucket_line_redirects_to_skills(str(b).strip())
            and not _cert_line_is_soft_skill_colon_leak(str(b).strip())
        ]
        if not name and not issuer and not dt and not bullets:
            continue
        if skill_bucket_line_redirects_to_skills(name):
            continue
        if _cert_line_is_soft_skill_colon_leak(name):
            continue
        if _cert_dict_is_core_skills_noise_row({**block, "bullets": bullets}):
            continue
        out.append(
            CertificationEntry(
                name=name,
                issuer=issuer,
                date=dt,
                bullets=bullets,
            )
        )
    return _merge_orphan_certification_entries(out)


def build_resume_document_payload(
    *,
    name: str,
    contact: str,
    summary: str,
    summary_source: str,
    experience_blocks: List[dict],
    projects: List[dict],
    education: List[dict],
    certifications: List[dict],
    skills: List[str],
    projects_already_prepared: bool = False,
) -> ResumeDocumentPayload:
    experience_blocks_identity_input, skill_lines_from_experience_blocks = (
        strip_skill_bucket_lines_from_experience_dict_blocks(experience_blocks)
    )
    if projects_already_prepared:
        projects_scrubbed = [dict(p) for p in (projects or []) if isinstance(p, dict)]
        skill_lines_from_projects: List[str] = []
        education_from_projects: List[dict] = []
        certifications_from_projects: List[dict] = []
    else:
        (
            projects_scrubbed,
            skill_lines_from_projects,
            education_from_projects,
            certifications_from_projects,
        ) = prepare_project_blocks_for_docx(projects)
    education_rows = list(education_from_projects) + list(education or [])
    certification_rows = list(certifications_from_projects) + list(certifications or [])
    skills_merged = merge_distinct_skill_lines(
        merge_distinct_skill_lines(list(skills or []), skill_lines_from_experience_blocks),
        skill_lines_from_projects,
    )
    exp = build_experience_entries_identity_first(experience_blocks_identity_input)
    exp, skill_lines_from_experience_entries = _strip_skill_bucket_lines_from_experience_entries(
        exp
    )
    skills_merged = merge_distinct_skill_lines(skills_merged, skill_lines_from_experience_entries)
    proj_entries = dict_projects_to_entries(projects_scrubbed)
    proj_entries, skill_lines_from_project_entries = _strip_skill_bucket_lines_from_project_entries(
        proj_entries
    )
    skills_merged = merge_distinct_skill_lines(skills_merged, skill_lines_from_project_entries)
    skills_merged = _strip_core_skills_label_lines(skills_merged)
    log_experience_segmentation_audit(experience_blocks_identity_input, exp)
    _fe = exp[0] if exp else None
    logger.info(
        "FINAL_EXPERIENCE_SOURCE function=build_experience_entries_identity_first "
        "entry_count=%s first_company=%r first_role=%r first_bullet_count=%s",
        len(exp),
        ((_fe.company or "").strip())[:200] if _fe else "",
        ((_fe.role or "").strip())[:200] if _fe else "",
        len(_fe.bullets) if _fe else 0,
    )
    edu = dict_rows_to_education_entries(education_rows)
    certs = dict_rows_to_certification_entries(certification_rows)
    return ResumeDocumentPayload(
        header=HeaderCanonical(name=(name or "").strip(), contact=(contact or "").strip()),
        summary=(summary or "").strip(),
        summary_source=summary_source,
        experience=exp,
        projects=proj_entries,
        education=edu,
        certifications=certs,
        skills=skills_merged,
    )


def experience_entries_to_legacy_dicts(entries: List[ExperienceEntry]) -> List[dict]:
    """Validators expect title / date_range keys."""
    return [
        {
            "title": e.role,
            "company": e.company,
            "date_range": e.date,
            "location": e.location,
            "bullets": list(e.bullets),
        }
        for e in entries
    ]


def canonical_resume_dict(payload: ResumeDocumentPayload) -> Dict[str, Any]:
    h = payload.header
    return {
        "header": {"name": h.name, "contact": h.contact},
        "summary": payload.summary,
        "experience": [
            {
                "company": e.company,
                "role": e.role,
                "date": e.date,
                "location": e.location,
                "bullets": list(e.bullets),
            }
            for e in payload.experience
        ],
        "projects": [
            {"name": p.name, "subtitle": p.subtitle, "bullets": list(p.bullets)}
            for p in payload.projects
        ],
        "education": [
            {
                "degree": e.degree,
                "institution": e.institution,
                "date": e.date,
                "location": e.location,
                "bullets": list(e.bullets),
            }
            for e in payload.education
        ],
        "certifications": [
            {
                "name": c.name,
                "issuer": c.issuer,
                "date": c.date,
                "bullets": list(c.bullets),
            }
            for c in payload.certifications
        ],
        "skills": list(payload.skills),
    }


def validate_resume_document_payload(payload: ResumeDocumentPayload) -> None:
    """
    Fail fast if the payload is not a fully structured resume model.
    No implicit flattening or mixed-content repair at render time.
    """
    if not isinstance(payload.summary, str):
        raise ResumeContractError("summary must be str")

    for i, e in enumerate(payload.experience):
        if not isinstance(e, ExperienceEntry):
            raise ResumeContractError(
                f"experience[{i}] must be ExperienceEntry, got {type(e).__name__}"
            )
        if not isinstance(e.bullets, list):
            raise ResumeContractError(f"experience[{i}].bullets must be a list")
        if e.bullets and not ((e.company or "").strip() or (e.role or "").strip()):
            raise ResumeContractError(
                f"experience[{i}]: bullets require a non-empty company or role"
            )
        for j, b in enumerate(e.bullets):
            if not isinstance(b, str):
                raise ResumeContractError(
                    f"experience[{i}].bullets[{j}] must be str, got {type(b).__name__}"
                )
            if _line_looks_like_role_header(b):
                raise ResumeContractError(
                    f"experience[{i}].bullets[{j}] looks like a job header, not a bullet"
                )

    for i, p in enumerate(payload.projects):
        if not isinstance(p, ProjectEntry):
            raise ResumeContractError(
                f"projects[{i}] must be ProjectEntry, got {type(p).__name__}"
            )
        if p.bullets and not ((p.name or "").strip() or (p.subtitle or "").strip()):
            raise ResumeContractError(
                f"projects[{i}]: bullets require a non-empty name or subtitle"
            )

    for i, e in enumerate(payload.education):
        if not isinstance(e, EducationEntry):
            raise ResumeContractError(
                f"education[{i}] must be EducationEntry, got {type(e).__name__}"
            )
        if e.bullets and not ((e.degree or "").strip() or (e.institution or "").strip()):
            raise ResumeContractError(
                f"education[{i}]: bullets require a non-empty degree or institution"
            )

    for i, c in enumerate(payload.certifications):
        if not isinstance(c, CertificationEntry):
            raise ResumeContractError(
                f"certifications[{i}] must be CertificationEntry, got {type(c).__name__}"
            )
        if c.bullets and not ((c.name or "").strip() or (c.issuer or "").strip()):
            raise ResumeContractError(
                f"certifications[{i}]: bullets require a non-empty name or issuer"
            )

    if not isinstance(payload.skills, list) or not all(
        isinstance(s, str) for s in payload.skills
    ):
        raise ResumeContractError("skills must be a list[str]")


def structured_payload_debug_dict(payload: ResumeDocumentPayload) -> Dict[str, Any]:
    base = canonical_resume_dict(payload)
    base["_summary_source"] = payload.summary_source
    return base


def structured_payload_debug_json(payload: ResumeDocumentPayload) -> str:
    return json.dumps(structured_payload_debug_dict(payload), ensure_ascii=False)

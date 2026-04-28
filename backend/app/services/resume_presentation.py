"""
Premium resume presentation rules: identity-forward summaries, impact ordering,
scannability, and lightweight artifact-quality signals.

These helpers do not replace grounding validation — callers must still run
export_docx._export_summary_passes_hygiene on any candidate summary string.
"""

from __future__ import annotations

import copy
import re
from typing import Any, Dict, List, Optional, Tuple

from app.services.rewrite_resume import _primary_job_title_from_resume, _trim_redundant_words

# Multi-word outcome phrases (substring-matched against corpus); avoid tool-stack framing.
_OUTCOME_PHRASES: Tuple[str, ...] = (
    "cross-functional collaboration",
    "cross-functional",
    "process improvement",
    "business requirements",
    "stakeholder management",
    "stakeholder engagement",
    "data quality",
    "regulatory compliance",
    "user acceptance testing",
    "business analysis",
    "system validation",
    "requirements gathering",
    "operational efficiency",
    "project delivery",
    "change management",
    "risk management",
    "data analysis",
    "reporting and analytics",
)

# Tool names that often produce weak “stack listing” summaries when overused.
_TOOL_TOKEN_RE = re.compile(
    r"(?i)\b(?:excel|power\s*bi|tableau|python|sql|vba|looker|snowflake|"
    r"azure|aws|gcp|bigquery|databricks|r\b)\b"
)

# Impact / ownership language (used for bullet scoring and summary heuristics).
_SIGNAL_PATTERNS: Tuple[Tuple[re.Pattern[str], float], ...] = (
    (re.compile(r"(?i)\b\d+%\b"), 4.0),
    (re.compile(r"(?i)\$[\d,.]+[kmb]?\b"), 4.0),
    (re.compile(r"(?i)\b\d{1,3}[,.]?\d*\s*(million|billion|k|m|users|customers|records)\b"), 3.5),
    (re.compile(r"(?i)\b(led|owned|spearheaded|directed|chaired|headed)\b"), 3.0),
    (re.compile(r"(?i)\b(reduced|increased|improved|accelerated|scaled|grew|cut)\b"), 2.5),
    (re.compile(r"(?i)\b(delivered|launched|drove|executed|implemented)\b"), 2.0),
    (re.compile(r"(?i)\b(cross-functional|stakeholder|executive|board|regulatory|sox|hipaa)\b"), 2.0),
    (re.compile(r"(?i)\b(ambiguous|turnaround|zero-to-one|greenfield|modernization)\b"), 2.5),
    (re.compile(r"(?i)\b(team|teams|people\s+manager|mentored|hired)\b"), 1.5),
)


# Phrases chosen in order for identity-forward export summaries (substring-matched on corpus).
_IDENTITY_EXPORT_PHRASES: Tuple[str, ...] = (
    "user acceptance testing",
    "system validation",
    "regulated environments",
    "regulatory compliance",
    "enterprise systems",
    "validation workflows",
    "structured delivery",
    "ambiguous requirements",
    "cross-functional collaboration",
    "cross-functional",
    "healthcare",
    "enterprise",
    "stakeholder management",
    "business analysis",
    "data quality",
    "project delivery",
    "requirements gathering",
    "business requirements",
    "operational efficiency",
)

_WEAK_OUTCOME_PAIR = frozenset({"operational efficiency", "business requirements"})

# Bare cross-functional + business analysis reads generic; prefer stronger corpus phrases.
_WEAK_OUTCOME_CROSSFUNCTIONAL_BUSINESS_ANALYSIS = frozenset(
    {"cross-functional", "business analysis"}
)


def build_structured_identity_export_summary(
    resume_data: Optional[dict], corpus: str
) -> str:
    """
    One sentence: structured first-job title + two corpus-grounded practice phrases.
    Prefers UAT / validation / compliance / collaboration signals over weak generic pairs.
    """
    if not resume_data or not isinstance(resume_data, dict) or not (corpus or "").strip():
        return ""
    cl = corpus.lower()
    title = _primary_job_title_from_resume(resume_data)
    if not title or len(title) < 8:
        return ""
    found: List[str] = []
    for p in _IDENTITY_EXPORT_PHRASES:
        if p in cl and p not in found:
            found.append(p)
    if len(found) < 2:
        return ""
    weak_l = {x.lower() for x in _WEAK_OUTCOME_PAIR}
    preferred = [p for p in found if p.lower() not in weak_l]
    if len(preferred) >= 2:
        a, b = preferred[0], preferred[1]
    elif len(preferred) == 1:
        a = preferred[0]
        b = next((p for p in found if p.lower() != a.lower()), found[-1])
    else:
        a, b = found[0], found[1]
    if frozenset({a.lower(), b.lower()}) == _WEAK_OUTCOME_CROSSFUNCTIONAL_BUSINESS_ANALYSIS:
        stronger = [p for p in found if p.lower() not in _WEAK_OUTCOME_CROSSFUNCTIONAL_BUSINESS_ANALYSIS]
        if len(stronger) >= 2:
            a, b = stronger[0], stronger[1]
        elif len(stronger) == 1 and len(found) >= 3:
            a, b = stronger[0], found[2]
        elif len(found) >= 3:
            a, b = found[0], found[2]
    elif a in _WEAK_OUTCOME_PAIR and b in _WEAK_OUTCOME_PAIR:
        stronger = [p for p in found if p not in _WEAK_OUTCOME_PAIR]
        if len(stronger) >= 2:
            a, b = stronger[0], stronger[1]
        elif len(stronger) == 1 and len(found) >= 3:
            a, b = stronger[0], found[2]
        elif len(found) >= 3:
            a, b = found[0], found[2]
    da = _phrase_display(corpus, a)
    db = _phrase_display(corpus, b)
    return _trim_redundant_words(f"{title} with experience in {da} and {db}.")


def build_strong_identity_forward_export_summary(
    resume_data: Optional[dict], corpus: str
) -> str:
    """
    One dense, identity-forward sentence when the resume clearly reads as senior BSA / UAT
    and the corpus contains the thematic anchors (substring checks only; no new facts).
    """
    if not resume_data or not isinstance(resume_data, dict) or not (corpus or "").strip():
        return ""
    cl = corpus.lower()
    title = _primary_job_title_from_resume(resume_data)
    if not title or len(title) < 10:
        return ""
    tl = title.lower()
    if not any(
        k in tl
        for k in (
            "business systems",
            "systems analyst",
            "uat",
            "quality",
            "validation",
        )
    ):
        return ""
    need = (
        ("enterprise" in cl and "systems" in cl)
        or "enterprise systems" in cl
        or (
            "enterprise" in cl
            and any(x in cl for x in ("software", "solutions", "platform", "applications"))
        )
        or "healthcare" in cl
    )
    need_val = (
        "user acceptance testing" in cl
        or re.search(r"(?i)\buat\b", cl) is not None
        or ("validation" in cl and ("workflow" in cl or "workflows" in cl))
        or "system validation" in cl
    )
    need_xfn = bool(re.search(r"cross[-\s]?functional", cl)) or (
        "stakeholder" in cl and ("team" in cl or "teams" in cl or "delivery" in cl)
    )
    need_reg = "regulated" in cl or "regulatory" in cl or "compliance" in cl
    if not (need and need_val and need_xfn and need_reg):
        return ""
    years_m = re.search(
        r"(?i)(?:(\d)\+?\s*years?\s+of\s+experience|(\d)\+?\s*years)(?!\s+old)",
        corpus,
    )
    years_bit = ""
    if years_m:
        g = years_m.group(1) or years_m.group(2)
        if g:
            years_bit = f"{g}+ years of "
    display_title = title.strip()
    if "uat" in tl and "/" not in display_title and "lead" not in tl:
        display_title = f"{display_title} / UAT Lead"
    if (
        ("end-to-end" in cl or "end to end" in cl)
        and ("ambiguous" in cl or "ambiguity" in cl)
        and ("high-stakes" in cl or "high stakes" in cl)
    ):
        body = (
            f"{years_bit}experience improving enterprise systems, leading end-to-end validation, "
            "and delivering structured solutions in ambiguous, high-stakes environments."
        )
    else:
        body = (
            f"{years_bit}experience improving enterprise systems, structuring validation workflows, "
            "and driving cross-functional delivery in regulated environments."
        )
    return _trim_redundant_words(f"{display_title} with {body}")


def infer_identity_role_label(resume_data: Optional[dict], corpus_lower: str) -> str:
    """Best-effort role line from structured data, else common titles in corpus."""
    t = _primary_job_title_from_resume(resume_data) if resume_data else ""
    if t and 3 <= len(t) <= 120:
        return t.strip()
    for r in (
        "business systems analyst",
        "business analyst",
        "data analyst",
        "product manager",
        "project manager",
        "program manager",
        "systems analyst",
    ):
        if r in corpus_lower:
            return " ".join(w.capitalize() for w in r.split())
    return "Professional"


def _phrase_display(corpus: str, phrase_lower: str) -> str:
    m = re.search(re.escape(phrase_lower), corpus, re.I)
    return m.group(0) if m else phrase_lower.title()


def build_outcome_phrase_export_summary(resume_data: dict, corpus: str) -> str:
    """
    One or two outcome phrases drawn as substrings from the corpus (identity-forward,
    not a tool list). Empty string if insufficient phrases.
    """
    cl = (corpus or "").lower()
    found: List[str] = []
    for p in _OUTCOME_PHRASES:
        if p in cl and p not in found:
            found.append(p)
        if len(found) >= 4:
            break
    # Prefer stronger identity signals before length tie-break among the rest.
    priority: List[str] = []
    for p in _IDENTITY_EXPORT_PHRASES:
        if p in found and p not in priority:
            priority.append(p)
    rest = [p for p in found if p not in priority]
    rest.sort(key=len, reverse=True)
    merged_order = priority + rest
    picked: List[str] = []
    for p in merged_order:
        if p not in picked:
            picked.append(p)
        if len(picked) >= 2:
            break
    if len(picked) >= 2:
        weak_test = frozenset(x.lower() for x in picked[:2])
        if weak_test == _WEAK_OUTCOME_CROSSFUNCTIONAL_BUSINESS_ANALYSIS:
            banned = _WEAK_OUTCOME_CROSSFUNCTIONAL_BUSINESS_ANALYSIS
            alt: List[str] = []
            for p in merged_order:
                if p.lower() in banned:
                    continue
                if p not in alt:
                    alt.append(p)
                if len(alt) >= 2:
                    break
            if len(alt) >= 2:
                picked = alt
            else:
                alt2: List[str] = []
                for p in merged_order:
                    if p.lower() == "business analysis":
                        continue
                    if p not in alt2:
                        alt2.append(p)
                    if len(alt2) >= 2:
                        break
                if len(alt2) >= 2:
                    picked = alt2
    role = infer_identity_role_label(resume_data, cl)
    if len(picked) >= 2:
        a = _phrase_display(corpus, picked[0])
        b = _phrase_display(corpus, picked[1])
        return _trim_redundant_words(f"{role} with experience in {a} and {b}.")
    if len(picked) == 1:
        a = _phrase_display(corpus, picked[0])
        return _trim_redundant_words(f"{role} with experience in {a}.")
    return ""


def is_tool_centric_summary(text: str) -> bool:
    """Heuristic: reads like a tool stack roll-call rather than role + outcomes."""
    s = (text or "").strip()
    if not s:
        return False
    tools = len(_TOOL_TOKEN_RE.findall(s.lower()))
    low = s.lower()
    if tools >= 3:
        return True
    if tools >= 2 and "with experience in" in low:
        return True
    return False


def bullet_impact_score(text: str) -> float:
    """Higher = stronger hiring signal for ordering only (not truth claims)."""
    t = text or ""
    score = 0.0
    for pat, w in _SIGNAL_PATTERNS:
        if pat.search(t):
            score += w
    if len(t) > 220:
        score -= 0.5
    return score


def prioritize_experience_blocks_for_export(blocks: List[dict]) -> List[dict]:
    """Stable-descending sort of bullets within each experience block by impact heuristics."""
    out: List[dict] = []
    for block in blocks or []:
        if not isinstance(block, dict):
            continue
        nb = copy.deepcopy(block)
        bullets = nb.get("bullets")
        if not isinstance(bullets, list) or len(bullets) < 2:
            out.append(nb)
            continue
        decorated: List[Tuple[float, int, str]] = []
        for i, b in enumerate(bullets):
            s = str(b).strip()
            decorated.append((bullet_impact_score(s), i, s))
        decorated.sort(key=lambda x: (-x[0], x[1]))
        nb["bullets"] = [t[2] for t in decorated]
        out.append(nb)
    return out


def prioritize_project_blocks_for_export(blocks: Optional[List[dict]]) -> List[dict]:
    """Same as experience, for portfolio bullets."""
    if not blocks:
        return []
    out: List[dict] = []
    for proj in blocks:
        if not isinstance(proj, dict):
            continue
        np = copy.deepcopy(proj)
        bullets = np.get("bullets")
        if not isinstance(bullets, list) or len(bullets) < 2:
            out.append(np)
            continue
        decorated: List[Tuple[float, int, str]] = []
        for i, b in enumerate(bullets):
            s = str(b).strip()
            decorated.append((bullet_impact_score(s), i, s))
        decorated.sort(key=lambda x: (-x[0], x[1]))
        np["bullets"] = [t[2] for t in decorated]
        out.append(np)
    return out


def trim_summary_for_scannability(summary: str, *, max_words: int = 52) -> str:
    """Cap length for screening speed; keeps whole words (caller re-validates hygiene)."""
    s = (summary or "").strip()
    words = s.split()
    if len(words) <= max_words:
        return s
    return " ".join(words[:max_words]).rstrip(",;:") + "."


def presentation_quality_warnings(
    *,
    summary: str,
    summary_source: str,
    experience_blocks: List[dict],
    skills_line: str,
    default_skills_placeholder: bool,
) -> List[str]:
    """Non-blocking presentation checks (logging / product telemetry)."""
    w: List[str] = []
    if is_tool_centric_summary(summary) and summary_source not in ("tailored",):
        w.append("summary_reads_tool_centric")
    if _looks_like_generic_skills_line(skills_line, default_skills_placeholder):
        w.append("skills_section_using_broad_default")
    eb = 0
    for block in experience_blocks or []:
        if not isinstance(block, dict):
            continue
        for b in block.get("bullets") or []:
            if str(b).strip():
                eb += 1
    if eb == 0:
        w.append("experience_has_no_bullets")
    return w


def _looks_like_generic_skills_line(line: str, is_default_placeholder: bool) -> bool:
    if is_default_placeholder:
        return True
    low = (line or "").lower()
    if "data & analytics:" in low and "sql" in low and "power bi" in low and len(low) < 120:
        return True
    return False


def section_integrity_sanity_hints(experience_blocks: List[dict]) -> List[str]:
    """Detect obvious cross-section leakage in payloads (debug / warnings)."""
    hints: List[str] = []
    bad = re.compile(r"(?i)@[\w.-]+\.|linkedin\.com|\(\d{3}\)\s*\d{3}")
    for block in experience_blocks or []:
        if not isinstance(block, dict):
            continue
        for b in block.get("bullets") or []:
            if bad.search(str(b)):
                hints.append("possible_contact_noise_in_experience_bullet")
                return hints
    return hints

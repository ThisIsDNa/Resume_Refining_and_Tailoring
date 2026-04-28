"""
Experience bullet ordering for export: rank by hiring-signal strength, reorder only.

Does not rewrite content or invent metrics — stable sort by score with original index tie-break.
Debug logging is gated by RESUME_TAILOR_EXPERIENCE_BULLET_PRIORITIZATION_DEBUG=1.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from typing import List, Literal, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

_DEBUG_ENV = "RESUME_TAILOR_EXPERIENCE_BULLET_PRIORITIZATION_DEBUG"


def experience_bullet_prioritization_debug_enabled() -> bool:
    return (os.environ.get(_DEBUG_ENV) or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


RoleTier = Literal["senior_lead", "analyst_specialist", "neutral"]


# --- Pattern groups: (regex, weight, tag) ---

_QUANT_PATTERNS: Tuple[Tuple[re.Pattern[str], float, str], ...] = (
    (re.compile(r"(?i)\b\d+%\b"), 5.0, "quant_pct"),
    (re.compile(r"(?i)\$[\d,.]+[kmb]?\b"), 5.0, "quant_money"),
    # "50+" — trailing \b after + fails before a space (both non-word chars)
    (re.compile(r"(?i)\b\d+\+"), 4.0, "quant_plus_count"),
    (re.compile(r"(?i)\b\d{1,3}(?:,\d{3})+\b"), 3.5, "quant_comma_number"),
    (re.compile(r"(?i)\b\d{1,4}\s*(?:million|billion|k|m|users|customers|records|tickets)\b"), 4.5, "quant_scale"),
)

_OWNERSHIP_PATTERNS: Tuple[Tuple[re.Pattern[str], float, str], ...] = (
    (
        re.compile(
            r"(?i)\b(?:led|owned|assumed|directed|drove|stabilized|resolved|spearheaded|headed|chaired)\b"
        ),
        4.0,
        "ownership",
    ),
    (re.compile(r"(?i)\b(?:executed|delivered|launched|implemented)\b"), 2.5, "delivery_verbs"),
)

_AMBIGUITY_RECOVERY_PATTERNS: Tuple[Tuple[re.Pattern[str], float, str], ...] = (
    (
        re.compile(
            r"(?i)\b(?:undocumented|at-risk|reverse[-\s]?engineered|rebuilt|clarified|turnaround|"
            r"legacy|rescued|stabiliz(?:e|ed|ing)|ambiguous)\b"
        ),
        4.5,
        "ambiguity_recovery",
    ),
)

_CROSS_FUNC_PATTERNS: Tuple[Tuple[re.Pattern[str], float, str], ...] = (
    (
        re.compile(
            r"(?i)\b(?:coordinated|liaised|liaison|partnered|aligned|client[-\s]?facing|"
            r"cross[-\s]?functional|stakeholders?|stakeholder)\b"
        ),
        3.5,
        "cross_functional",
    ),
)

_REGULATED_ENTERPRISE_PATTERNS: Tuple[Tuple[re.Pattern[str], float, str], ...] = (
    (
        re.compile(
            r"(?i)\b(?:healthcare|hipaa|sox|sla|compliance|regulatory|production|enterprise|"
            r"platform|audit(?:ed|ing)?)\b"
        ),
        3.0,
        "regulated_enterprise",
    ),
)

# Initiative / delivery signals common on senior BSA + UAT resumes (export ordering only).
_BSA_INITIATIVE_HINTS: Tuple[Tuple[re.Pattern[str], float, str], ...] = (
    (re.compile(r"(?i)\b50\+\b"), 2.5, "initiative_sla_volume"),
    (re.compile(r"(?i)\bprovider\s+portal\b"), 2.5, "initiative_portal"),
    (re.compile(r"(?i)\$[\d,.]+\s*(?:m|million)\b"), 3.0, "initiative_money"),
    (re.compile(r"(?i)\b6\s*million\b"), 3.0, "initiative_money_word"),
    (re.compile(r"(?i)\b(?:s\.m\.e\.|subject\s+matter\s+expert)\b"), 2.0, "initiative_sme"),
    (re.compile(r"(?i)\b(?:review\s+framework|qa\s+framework|defect\s+triage)\b"), 2.0, "initiative_qa"),
)

_OUTCOME_PATTERNS: Tuple[Tuple[re.Pattern[str], float, str], ...] = (
    (
        re.compile(
            r"(?i)\b(?:reduced|improved|restored|secured|increased|enabled|accelerated|"
            r"cut|grew|scaled|streamlined|optimized|eliminated|mitigated)\b"
        ),
        3.0,
        "outcome",
    ),
)

# Weak / generic participation (penalty when dominant)
_GENERIC_WEAK_PATTERNS: Tuple[Tuple[re.Pattern[str], float, str], ...] = (
    (re.compile(r"(?i)^\s*(?:supported|assisted|helped)\b"), 2.5, "generic_opening"),
    (re.compile(r"(?i)\bworked\s+on\b"), 2.0, "worked_on"),
)

_TOOL_TOKEN_RE = re.compile(
    r"(?i)\b(?:excel|power\s*bi|tableau|python|sql|vba|looker|snowflake|"
    r"azure|aws|gcp|bigquery|databricks|jira|confluence|salesforce)\b"
)

_SENIOR_ROLE_HINT = re.compile(
    r"(?i)\b(?:senior|sr\.?|lead|principal|staff|director|head\s+of|vp|vice\s+president|"
    r"chief|manager|program\s+manager|product\s+owner)\b"
)
_ANALYST_ROLE_HINT = re.compile(
    r"(?i)\b(?:analyst|specialist|associate|coordinator|uat|business\s+systems)\b"
)

# Senior-tier nudges: extra weight when role looks senior/lead
_SENIOR_BOOST_PATTERNS: Tuple[Tuple[re.Pattern[str], float, str], ...] = (
    (re.compile(r"(?i)\b(?:owned|directed|drove|decision|stakeholders?|roadmap|prioritized)\b"), 1.5, "senior_ownership"),
    (_AMBIGUITY_RECOVERY_PATTERNS[0][0], 1.0, "senior_turnaround"),
    (re.compile(r"(?i)\b(?:mentored|hired|managed|supervised)\b"), 1.5, "senior_leadership"),
)

# Analyst-tier nudges
_ANALYST_BOOST_PATTERNS: Tuple[Tuple[re.Pattern[str], float, str], ...] = (
    (re.compile(r"(?i)\b(?:validated|validation|uat|test\s+plan|requirements|process)\b"), 1.5, "analyst_quality"),
    (_OUTCOME_PATTERNS[0][0], 0.8, "analyst_outcome"),
    (re.compile(r"(?i)\b(?:documented|traceability|defects?|gaps?)\b"), 1.2, "analyst_detail"),
)


def infer_role_tier(role: str) -> RoleTier:
    r = (role or "").strip().lower()
    if not r:
        return "neutral"
    # Senior / Lead in title (e.g. Senior BSA, UAT Lead) → ownership & turnaround nudges
    if re.search(r"(?i)\b(?:senior|sr\.?|lead)\b", r):
        return "senior_lead"
    if _ANALYST_ROLE_HINT.search(r):
        return "analyst_specialist"
    if _SENIOR_ROLE_HINT.search(r):
        return "senior_lead"
    return "neutral"


def _bullet_similarity(a: str, b: str) -> float:
    """Cheap token Jaccard for near-duplicate penalty."""
    ta = set(re.findall(r"[a-z0-9]+", (a or "").lower()))
    tb = set(re.findall(r"[a-z0-9]+", (b or "").lower()))
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    union = len(ta | tb)
    return inter / union if union else 0.0


@dataclass
class BulletScoreDetail:
    index: int
    text: str
    score: float
    tags: List[str] = field(default_factory=list)


@dataclass
class ExperienceBulletPrioritizationDebug:
    company: str
    role: str
    role_tier: RoleTier
    original_indices: List[int]
    prioritized_indices: List[int]
    details: List[BulletScoreDetail]
    top_rationale: str


def score_experience_bullet(
    text: str,
    *,
    role_tier: RoleTier,
    other_bullets: Sequence[str],
    self_index: int,
) -> Tuple[float, List[str]]:
    """Return (score, reason tags) for one bullet. Higher = surface earlier."""
    t = (text or "").strip()
    tags: List[str] = []
    score = 0.0

    def apply_group(group: Tuple[Tuple[re.Pattern[str], float, str], ...]) -> None:
        nonlocal score
        for pat, w, tag in group:
            if pat.search(t):
                score += w
                if tag not in tags:
                    tags.append(tag)

    apply_group(_QUANT_PATTERNS)
    apply_group(_OWNERSHIP_PATTERNS)
    apply_group(_AMBIGUITY_RECOVERY_PATTERNS)
    apply_group(_CROSS_FUNC_PATTERNS)
    apply_group(_REGULATED_ENTERPRISE_PATTERNS)
    apply_group(_BSA_INITIATIVE_HINTS)
    apply_group(_OUTCOME_PATTERNS)

    for pat, pen, tag in _GENERIC_WEAK_PATTERNS:
        if pat.search(t):
            score -= pen
            tags.append(f"penalty:{tag}")

    # Tool-heavy without outcome/quant: de-prioritize stack listings
    tool_hits = len(_TOOL_TOKEN_RE.findall(t))
    has_strong_signal = any(
        tg.startswith("quant_") or tg in ("outcome", "ownership", "ambiguity_recovery")
        for tg in tags
    )
    if tool_hits >= 2 and not has_strong_signal and len(t) < 160:
        score -= 3.0 * min(tool_hits - 1, 3)
        tags.append("penalty:tool_only")

    # Length: extremely long bullets scan poorly; mild penalty
    if len(t) > 320:
        score -= 1.0
        tags.append("penalty:long")

    # Role-tier nudges
    if role_tier == "senior_lead":
        for pat, w, tag in _SENIOR_BOOST_PATTERNS:
            if pat.search(t):
                score += w
                if tag not in tags:
                    tags.append(tag)
    elif role_tier == "analyst_specialist":
        for pat, w, tag in _ANALYST_BOOST_PATTERNS:
            if pat.search(t):
                score += w
                if tag not in tags:
                    tags.append(tag)

    # Near-duplicate penalty vs other bullets
    for j, other in enumerate(other_bullets):
        if j == self_index:
            continue
        sim = _bullet_similarity(t, other)
        if sim >= 0.55:
            score -= 2.5 * sim
            tags.append("penalty:near_duplicate")
            break

    return score, tags


def prioritize_experience_bullets(
    bullets: Sequence[str],
    *,
    company: str = "",
    role: str = "",
    date: str = "",
    location: str = "",
) -> Tuple[List[str], Optional[ExperienceBulletPrioritizationDebug]]:
    """
    Reorder bullets by hiring-signal score (stable: preserve original order on ties).

    Returns (reordered_bullets, debug_or_none).
    """
    raw = [str(b).strip() for b in bullets if str(b).strip()]
    if len(raw) <= 1:
        return list(raw), None

    role_tier = infer_role_tier(role)
    n = len(raw)
    scored: List[Tuple[float, int, List[str]]] = []
    for i, b in enumerate(raw):
        s, tags = score_experience_bullet(
            b,
            role_tier=role_tier,
            other_bullets=raw,
            self_index=i,
        )
        scored.append((s, i, tags))

    # Sort: highest score first, then original index
    order = sorted(range(n), key=lambda k: (-scored[k][0], scored[k][1]))
    reordered = [raw[i] for i in order]

    debug: Optional[ExperienceBulletPrioritizationDebug] = None
    if experience_bullet_prioritization_debug_enabled():
        details = [
            BulletScoreDetail(
                index=i,
                text=raw[i],
                score=scored[i][0],
                tags=scored[i][2],
            )
            for i in range(n)
        ]
        top_idx = order[0]
        top_tags = ", ".join(scored[top_idx][2][:8]) if scored[top_idx][2] else "(no tags)"
        rationale = (
            f"top bullet idx {top_idx} score={scored[top_idx][0]:.2f} tags=[{top_tags}] "
            f"tier={role_tier}"
        )
        debug = ExperienceBulletPrioritizationDebug(
            company=(company or "").strip(),
            role=(role or "").strip(),
            role_tier=role_tier,
            original_indices=list(range(n)),
            prioritized_indices=order,
            details=details,
            top_rationale=rationale,
        )
        logger.info(
            "EXPERIENCE_BULLET_PRIORITIZATION company=%r role=%r tier=%s",
            company,
            role,
            role_tier,
        )
        logger.info(
            "  original_order: %s",
            [raw[i][:72] + ("…" if len(raw[i]) > 72 else "") for i in range(n)],
        )
        logger.info(
            "  prioritized_order: %s",
            [reordered[j][:72] + ("…" if len(reordered[j]) > 72 else "") for j in range(n)],
        )
        for i in range(n):
            d = details[i]
            logger.info(
                "  bullet[%d] score=%.2f tags=%s",
                d.index,
                d.score,
                d.tags,
            )
        logger.info("  %s", rationale)

    return reordered, debug


def prioritize_experience_entry_bullets(
    company: str,
    role: str,
    bullets: Sequence[str],
    *,
    date: str = "",
    location: str = "",
) -> Tuple[List[str], Optional[ExperienceBulletPrioritizationDebug]]:
    """Convenience wrapper using ExperienceEntry-style fields."""
    return prioritize_experience_bullets(
        bullets,
        company=company,
        role=role,
        date=date,
        location=location,
    )

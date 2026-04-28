"""
Compares extracted resume signals against role templates and produces gap classifications plus recommended actions.

Coach-style outputs are template-backed and tied to observed signals — no fabricated jobs.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set, Tuple

from app.services.gap_analysis.role_templates import RoleProfile, get_role_profile
from app.services.gap_analysis.signals_catalog import SIGNAL_CATALOG
from app.services.gap_analysis.signal_extractor import extract_resume_signals

# ---------------------------------------------------------------------------
# Classification: missing signals (absent from evidence index)
# ---------------------------------------------------------------------------

# Absent signals that can usually be demonstrated with artifacts / sample work.
_PORTFOLIO_BUILDABLE_IDS: Set[str] = {
    "sql_data",
    "metrics_dashboards",
    "metrics_reporting",
    "reporting_dashboard_ownership",
    "reporting_automation",
    "financial_modeling",
    "experimentation_ab",
    "pilots_and_experiments",
    "workflow_optimization",
    "operating_cadence",
    "vendor_management",
    "cross_functional_coordination",
    "process_improvement",
    "operational_excellence",
    "roadmapping",
}

# Absent signals that typically need real role exposure to defend in interview.
_EXPERIENCE_FIRST_IDS: Set[str] = {
    "stakeholder_communication",
    "executive_readouts",
    "business_partnering",
    "user_research_signals",
    "product_discovery",
}


def _signal_index(evidence: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {str(e["signal_id"]): e for e in evidence if e.get("signal_id")}


def _partial_resume_hit(signal_id: str, combined_lower: str) -> bool:
    spec = SIGNAL_CATALOG.get(signal_id)
    if not spec:
        return False
    for kw in spec["keywords"]:
        if kw.lower() in combined_lower:
            return True
    return False


def _classify_missing_gap(signal_id: str, *, partial: bool) -> str:
    """Absent signal: thin wording vs portfolio vs real-world exposure."""
    if partial:
        return "resume_fixable"
    if signal_id in _EXPERIENCE_FIRST_IDS:
        return "experience_gap"
    spec = SIGNAL_CATALOG.get(signal_id)
    tool_like = bool(spec and spec.get("tool_like"))
    if tool_like or signal_id in _PORTFOLIO_BUILDABLE_IDS:
        return "project_needed"
    return "experience_gap"


def _weak_match_portfolio_hint(signal_id: str) -> bool:
    """Weak evidence can still be bolstered with a tight artifact (coach-style)."""
    if signal_id == "user_research_signals":
        return True
    spec = SIGNAL_CATALOG.get(signal_id)
    if not spec:
        return False
    if spec.get("tool_like"):
        return True
    return signal_id in _PORTFOLIO_BUILDABLE_IDS


def _weak_match_skill_hint(
    signal_id: str,
    strength_level: Optional[str],
) -> bool:
    if strength_level == "thin":
        return True
    spec = SIGNAL_CATALOG.get(signal_id)
    if spec and spec.get("tool_like"):
        return True
    if strength_level == "moderate" and _weak_match_portfolio_hint(signal_id):
        return True
    if strength_level == "moderate":
        return True
    return False


def _actions_for_weak_match(
    signal_id: str,
    label: str,
    strength_level: Optional[str],
) -> Tuple[str, Optional[str], Optional[str]]:
    """Every weak match gets a resume line; portfolio + learning hints when appropriate."""
    strength = (strength_level or "thin").strip().lower()
    resume_change = (
        f"Elevate **{label}** on your resume: add a bullet with scope, metric, and decision impact "
        f"so this capability reads as core — current evidence looks **{strength}** relative to the role bar."
    )
    project: Optional[str] = None
    if _weak_match_portfolio_hint(signal_id):
        project = (
            f"Create a concise portfolio artifact (one-pager, deck appendix, or repo README) that walks through "
            f"**{label}** end-to-end with inputs, method, and outcome — interviewers can skim it in two minutes."
        )
    skill: Optional[str] = None
    if _weak_match_skill_hint(signal_id, strength_level):
        if strength == "thin" or (SIGNAL_CATALOG.get(signal_id) or {}).get("tool_like"):
            skill = (
                f"Close the learning gap on **{label}** with a short structured course or guided exercises, "
                f"then reuse the same vocabulary you will use in interviews."
            )
        else:
            skill = (
                f"Rehearse one STAR story for **{label}** that quantifies trade-offs and stakeholders so moderate "
                f"evidence feels decisive, not decorative."
            )
    return resume_change, project, skill


def _actions_for_missing_gap(
    signal_id: str,
    gap_category: str,
    label: str,
) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    resume_change: Optional[str] = None
    project: Optional[str] = None
    skill: Optional[str] = None
    if gap_category == "resume_fixable":
        resume_change = (
            f"Surface **{label}** explicitly: weave keywords from your real work into a bullet with outcome and "
            "owner language — avoid implying depth you have not lived."
        )
        skill = (
            f"Align vocabulary for **{label}** with how this role describes the work, only where your history supports it."
        )
    elif gap_category == "project_needed":
        project = (
            f"Ship a small, documented artifact (repo, one-pager, or case write-up) that demonstrates **{label}** "
            "with assumptions, data, and a clear decision or recommendation."
        )
        skill = f"Practice **{label}** on a public dataset or sandbox so you can walk through mechanics credibly."
    else:
        resume_change = (
            f"Do not imply **{label}** until you have real examples; seek a stretch assignment, shadowing, or volunteer "
            "work you can later cite with specifics."
        )
        skill = f"Study how **{label}** shows up day-to-day in this role and map one honest next step to close the gap."
    return resume_change, project, skill


def _fit_summary(
    role: RoleProfile,
    *,
    strong_n: int,
    weak_n: int,
    miss_n: int,
    weak_required_thin_n: int,
) -> str:
    header = (
        f"Compared your resume to the **{role.display_name}** profile: "
        f"{strong_n} strong capability matches, {weak_n} areas with thin or indirect evidence, "
        f"and {miss_n} required signals not clearly demonstrated in the text provided."
    )
    parts: List[str] = [header]
    thin_not_missing = miss_n == 0 and weak_required_thin_n > 0
    if thin_not_missing:
        parts.append(
            "No required signals are fully missing, but several are thin and should be strengthened before you "
            "position yourself as a strong match."
        )
    if miss_n == 0 and weak_n > 0 and not thin_not_missing and weak_required_thin_n == 0:
        parts.append(
            "Optional profile signals are not yet evidenced in your file — add them only where you can defend them with examples."
        )
    if miss_n == 0 and weak_n == 0:
        parts.append("Overall fit looks solid on the signals we can verify from your materials.")
    if miss_n > 0:
        parts.append(
            "Prioritize closing missing capabilities with targeted work, artifacts, or resume lines that cite real "
            "outcomes — avoid claiming experience you cannot support in an interview."
        )
    if miss_n > 0 and weak_required_thin_n > 0:
        parts.append(
            "Even where nothing is fully absent, thin required signals still need sharper proof to feel credible."
        )
    return " ".join(parts)


def _dedupe_append(target: List[str], seen: Set[str], line: Optional[str]) -> None:
    if not line or not str(line).strip():
        return
    s = str(line).strip()
    if s in seen:
        return
    seen.add(s)
    target.append(s)


def _attach_action_stable_ids(actions: Dict[str, Any]) -> None:
    """
    Deterministic ids per action line for future selective-apply UX.
    Parallel to resume_changes / project_suggestions / skill_recommendations (same order, same length).
    """
    rc = actions.get("resume_changes") or []
    actions["resume_change_items"] = [
        {"id": f"refinery_action_resume_{i}", "text": str(t)} for i, t in enumerate(rc)
    ]
    pj = actions.get("project_suggestions") or []
    actions["project_suggestion_items"] = [
        {"id": f"refinery_action_project_{i}", "text": str(t)} for i, t in enumerate(pj)
    ]
    sk = actions.get("skill_recommendations") or []
    actions["skill_recommendation_items"] = [
        {"id": f"refinery_action_skill_{i}", "text": str(t)} for i, t in enumerate(sk)
    ]


def _ensure_actions_nonempty(
    actions: Dict[str, Any],
    *,
    has_gaps: bool,
) -> None:
    if not has_gaps:
        return
    if (
        actions["resume_changes"]
        or actions["project_suggestions"]
        or actions["skill_recommendations"]
    ):
        return
    actions["resume_changes"].append(
        "Pick the highest-impact gap above and add one bullet that ties scope, metric, and stakeholder to a "
        "verifiable story you can speak to for five minutes."
    )


def build_gap_report(
    resume_data: Dict[str, Any],
    role_template_id: str,
    *,
    job_description: str = "",
) -> Dict[str, Any]:
    extracted = extract_resume_signals(resume_data)
    role = get_role_profile(role_template_id)
    idx = _signal_index(list(extracted["evidence_signals"]))

    blobs: List[str] = []
    sections = resume_data.get("sections") or {}
    for k in ("summary", "experience", "projects", "skills"):
        v = sections.get(k) or resume_data.get(k)
        if isinstance(v, list):
            blobs.append("\n".join(str(x) for x in v if x))
        elif isinstance(v, str):
            blobs.append(v)
    raw = resume_data.get("raw_text")
    if isinstance(raw, str):
        blobs.append(raw)
    combined_lower = "\n".join(blobs).lower()

    jd_lower = (job_description or "").lower()
    jd_tokens = set(re.findall(r"[a-z]{4,}", jd_lower))

    strong_matches: List[Dict[str, Any]] = []
    weak_matches: List[Dict[str, Any]] = []
    missing_signals: List[Dict[str, Any]] = []

    ordered: List[Tuple[str, bool]] = []
    seen: Set[str] = set()
    for sid in role.required_signals:
        if sid not in seen:
            ordered.append((sid, True))
            seen.add(sid)
    for sid in role.nice_to_have_signals:
        if sid not in seen:
            ordered.append((sid, False))
            seen.add(sid)

    for sid, is_required in ordered:
        spec = SIGNAL_CATALOG.get(sid)
        if not spec:
            continue
        ev = idx.get(sid)
        if ev and ev.get("strength_level") == "strong":
            strong_matches.append(
                {
                    "signal_id": sid,
                    "label": spec["label"],
                    "strength_level": "strong",
                    "priority": "required" if is_required else "nice_to_have",
                    "notes": "Clear match in resume text.",
                }
            )
            continue
        if ev and ev.get("strength_level") in ("moderate", "thin"):
            weak_matches.append(
                {
                    "signal_id": sid,
                    "label": spec["label"],
                    "strength_level": ev.get("strength_level"),
                    "priority": "required" if is_required else "nice_to_have",
                    "notes": "Present but would benefit from stronger, role-specific proof.",
                }
            )
            continue
        if not is_required:
            weak_matches.append(
                {
                    "signal_id": sid,
                    "label": spec["label"],
                    "strength_level": None,
                    "priority": "nice_to_have",
                    "notes": "Optional capability for this profile — not evidenced in resume text.",
                }
            )
            continue
        partial = _partial_resume_hit(sid, combined_lower)
        jd_hint = any(
            t in jd_tokens for t in re.findall(r"[a-z]{4,}", " ".join(spec["keywords"]).lower())
        )
        notes = "Not observed in resume sections we scanned."
        if jd_hint and jd_lower.strip():
            notes += (
                " Job description mentions related themes — align resume bullets to those terms "
                "only where truthful."
            )
        missing_signals.append(
            {
                "signal_id": sid,
                "label": spec["label"],
                "strength_level": None,
                "notes": notes,
                "required": True,
            }
        )

    classified: List[Dict[str, Any]] = []
    resume_changes: List[str] = []
    project_suggestions: List[str] = []
    skill_recommendations: List[str] = []
    seen_resume: Set[str] = set()
    seen_proj: Set[str] = set()
    seen_skill: Set[str] = set()

    for m in missing_signals:
        sid = str(m["signal_id"])
        partial = _partial_resume_hit(sid, combined_lower)
        cat = _classify_missing_gap(sid, partial=partial)
        classified.append(
            {
                "signal_id": sid,
                "label": m["label"],
                "gap_category": cat,
                "rationale": (
                    "Related wording may exist but is too thin to count as proof."
                    if partial
                    else "No grounded evidence line found in resume text for this capability."
                ),
            }
        )
        rc, pj, sk = _actions_for_missing_gap(sid, cat, str(m["label"]))
        _dedupe_append(resume_changes, seen_resume, rc)
        _dedupe_append(project_suggestions, seen_proj, pj)
        _dedupe_append(skill_recommendations, seen_skill, sk)

    weak_required_thin_n = 0
    for wm in weak_matches:
        sid = str(wm["signal_id"])
        label = str(wm["label"])
        pri = str(wm.get("priority") or "")
        sl = wm.get("strength_level")
        if pri == "required" and sl in ("thin", "moderate"):
            weak_required_thin_n += 1
            classified.append(
                {
                    "signal_id": sid,
                    "label": label,
                    "gap_category": "resume_fixable",
                    "rationale": (
                        f"Required capability is present but reads as **{sl}** — tighten proof before claiming strength."
                    ),
                }
            )
        rc, pj, sk = _actions_for_weak_match(sid, label, sl if isinstance(sl, str) else None)
        _dedupe_append(resume_changes, seen_resume, rc)
        _dedupe_append(project_suggestions, seen_proj, pj)
        _dedupe_append(skill_recommendations, seen_skill, sk)

    miss_n = len([x for x in missing_signals if x.get("required")])
    fit_summary = _fit_summary(
        role,
        strong_n=len(strong_matches),
        weak_n=len(weak_matches),
        miss_n=miss_n,
        weak_required_thin_n=weak_required_thin_n,
    )

    actions: Dict[str, Any] = {
        "resume_changes": resume_changes,
        "project_suggestions": project_suggestions,
        "skill_recommendations": skill_recommendations,
    }
    _ensure_actions_nonempty(actions, has_gaps=bool(weak_matches or missing_signals))
    _attach_action_stable_ids(actions)

    return {
        "fit_summary": fit_summary,
        "gaps": {
            "strong_matches": strong_matches,
            "weak_matches": weak_matches,
            "missing_signals": missing_signals,
            "classified": classified,
            "resume_signals": {
                "strengths": extracted["strengths"],
                "tools": extracted["tools"],
                "evidence_signals": extracted["evidence_signals"],
            },
        },
        "actions": actions,
        "meta": {
            "role_template_id": role.id,
            "role_display_name": role.display_name,
        },
    }


def analyze_resume_gap_report(
    resume_data: Dict[str, Any],
    role_template_id: str,
    *,
    job_description: str = "",
) -> Dict[str, Any]:
    """Public entry: full coach-style gap JSON."""
    return build_gap_report(resume_data, role_template_id, job_description=job_description)

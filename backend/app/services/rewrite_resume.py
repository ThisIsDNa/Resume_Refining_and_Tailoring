"""Rewrite / tailor resume content using only grounded, mapped evidence (no fabrication)."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from app.services.parse_job import (
    is_actionable_requirement_line,
    is_benefits_line,
    is_company_about_line,
    is_generic_responsibility_line,
    is_heading_like_line,
    is_manifesto_or_values_line,
    is_marketing_or_manifesto_line,
    is_philosophy_like_line,
    is_requirement_grade_candidate,
    requirement_allowed_in_pipeline,
)
from app.utils.text_cleaning import normalize_whitespace

# ---------------------------------------------------------------------------
# Known tech / product phrases for conservative tool-preservation checks (lowercase)
# Longer phrases first for greedy matching.
# ---------------------------------------------------------------------------

_KNOWN_TECH_PHRASES: Tuple[str, ...] = (
    "power bi",
    "powerbi",
    "t-sql",
    "tsql",
    "machine learning",
    "ms sql",
    "microsoft excel",
    "google analytics",
    "azure data factory",
    "sql server",
    "excel",
    "tableau",
    "looker",
    "snowflake",
    "databricks",
    "kubernetes",
    "terraform",
    "jenkins",
    "react",
    "angular",
    "vue",
    "node.js",
    "nodejs",
    "typescript",
    "javascript",
    "python",
    "pandas",
    "numpy",
    "pyspark",
    "spark",
    "hadoop",
    "kafka",
    "airflow",
    "dbt",
    "etl",
    "sql",
    "aws",
    "gcp",
    "azure",
    "docker",
    "git",
    "jira",
    "salesforce",
    "sap",
    "r",
)

# Leadership / ownership escalation (whole-word style checks)
_STRONG_OWNERSHIP_WORDS = frozenset(
    """
    led lead leading owns owned owning spearhead spearheaded directed drives drove driving
    managed managing head headed chair chaired oversee oversaw overseeing pioneered
    transformed transformation enterprise-wide enterprisewide org-wide organization-wide
    """.split()
)

_NUMERIC_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])(?:\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)(?:%|k|m|bn)?(?![A-Za-z0-9])",
    re.I,
)

# Lightweight verb / readability checks (deterministic, no NLP deps)
_COMMON_VERBS_RE = re.compile(
    r"\b(?:is|are|was|were|be|been|being|have|has|had|do|does|did|done|will|would|could|should|may|might|can|must|"
    r"work|worked|working|lead|led|leading|manage|managed|managing|build|built|building|create|created|creating|"
    r"develop|developed|developing|design|designed|designing|support|supported|supporting|analyze|analyzed|analyzing|"
    r"implement|implemented|implementing|deliver|delivered|delivering|drive|drove|driving|own|owned|owning|"
    r"collaborate|collaborated|collaborating|improve|improved|improving|reduce|reduced|reducing|increase|increased|increasing|"
    r"execute|executed|executing|perform|performed|performing|ensure|ensured|ensuring|enable|enabled|enabling|"
    r"validate|validated|validating|report|reported|reporting|coordinate|coordinated|coordinating|"
    r"show|shown|shows|appear|appears|reflect|reflects|reflected|provide|provides|provided|see)\b",
    re.I,
)

_SUMMARY_META_BAD = re.compile(
    r"(related terms that appear|terms that appear|keywords? (?:already |)listed|keyword(?:s)?\s*(?:include|are)|"
    r"meta[- ]description|as shown in this resume,?\s*the following)",
    re.I,
)
_SUMMARY_META_EXTRA = re.compile(
    r"\b("
    r"this resume|on this resume|in this document|listed above|see below|as follows|"
    r"related terms|key skills?|skills?:\s*$|experience includes:|"
    r"phone\s*:|email\s*:|linkedin\.com"
    r")\b",
    re.I,
)
_SUMMARY_EMAIL = re.compile(
    r"[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}",
    re.I,
)
_SUMMARY_PHONE = re.compile(
    r"(?:\+?\d{1,3}[\s.\-]?)?(?:\(\d{3}\)|\d{3})[\s.\-]?\d{3}[\s.\-]?\d{4}\b|\b\d{3}[\s.\-]\d{3}[\s.\-]\d{4}\b",
)
_SUMMARY_URL = re.compile(
    r"https?://\S+|www\.\S+|linkedin\.com/\S+|github\.com/\S+",
    re.I,
)

# For shuffle detection: short function words only (not theme debris).
_READ_STOP = frozenset(
    "the a an and or for of in to with on at by as is was are be been has have had "
    "their our your this that these those".split()
)

# Tokens that must not anchor a summary theme (keyword-list debris, ordinals, etc.)
_SUMMARY_THEME_STOP = frozenset(
    """
    one two three four five first second related terms keywords include including
    intelligence listed appears appear various multiple several variously
    """.split()
)
# Keywords that must not become naked summary “themes” (certs / noise)
_SUMMARY_KEYWORD_SKIP = frozenset(
    """
    pmp cpa cfa cissp comptia scrum aws gcp azure certified certification
    benefits compensation perks equity salary pto vacation insurance bonus
    """.split()
)

_SUMMARY_BENEFITS_OR_OFFER = re.compile(
    r"\b(generous\s+benefits|competitive\s+compensation|health\s+dental\s+vision|unlimited\s+pto|"
    r"401\s*\(?k\)?\s+match|total\s+rewards|what\s+we\s+offer|employee\s+perks)\b",
    re.I,
)
_SUMMARY_JD_POLLUTION = re.compile(
    r"\b(our\s+values|we\s+believe|our\s+mission|employment\s+type|competitive\s+salary|"
    r"health\s+and\s+dental|why\s+join\s+us)\b",
    re.I,
)


def _requirement_text_in_validated_set(rt: str, job_signals: Optional[dict]) -> bool:
    """Authoritative gate: actionable + validated_requirements membership when present."""
    return requirement_allowed_in_pipeline(str(rt or ""), job_signals)


def _count_clean_requirements_in_signals(job_signals: dict) -> int:
    """Count canonical validated_requirements only (same list as map + output)."""
    vr = job_signals.get("validated_requirements")
    if isinstance(vr, list) and vr:
        return len([x for x in vr if str(x).strip()])
    return 0


def _summary_input_has_jd_pollution(text: str) -> bool:
    """Benefits, about, manifesto, employer-marketing, or vague JD responsibility fluff — do not use in summary."""
    t = (text or "").strip()
    if not t:
        return False
    if re.search(r"\bbackground\s+aligns\s+with\b", t, re.I):
        return True
    if _SUMMARY_BENEFITS_OR_OFFER.search(t) or _SUMMARY_JD_POLLUTION.search(t):
        return True
    if is_benefits_line(t) or is_company_about_line(t) or is_manifesto_or_values_line(t):
        return True
    if is_philosophy_like_line(t) or is_marketing_or_manifesto_line(t):
        return True
    if is_generic_responsibility_line(t):
        return True
    for sent in re.split(r"(?<=[.!?])\s+", t):
        s = sent.strip()
        if not s:
            continue
        if is_generic_responsibility_line(s):
            return True
        if is_philosophy_like_line(s) or is_marketing_or_manifesto_line(s):
            return True
        if is_company_about_line(s) or is_manifesto_or_values_line(s):
            return True
    return False


_SUMMARY_JD_COPY_PATTERNS = re.compile(
    r"(?i)\b(?:support(?:ing)?\s+cross-?functional\s+teams|proficiency\s+in\s+excel|"
    r"collaborate\s+with\s+teams|improve\s+business\s+operations|work\s+with\s+teams\s+to|"
    r"assist\s+with\s+the\s+|demonstrated\s+proficiency\s+in)\b"
)

_SUMMARY_LEXICON_ALLOW = frozenset(
    """
    professional experience settings delivery documentation analysis reporting validation stakeholder
    business enterprise team teams collaboration structured hands-on applying centered related supports
    including skilled skill skills additional depth includes work works contexts environments
    stakeholder-facing cross-functional documentation system systems data analytics excel sql python
    enterprise applying professional with and for the from into additional depth delivery
    team handoffs healthcare government financial retail
    """.split()
)


def _summary_has_forbidden_jd_copy_patterns(text: str) -> bool:
    return bool(_SUMMARY_JD_COPY_PATTERNS.search(text or ""))


def _summary_words_grounded_in_resume(summary: str, corpus_lower: str) -> bool:
    cl = corpus_lower or ""
    for m in re.finditer(r"[A-Za-z][A-Za-z0-9+#.\-]{3,}", summary or ""):
        # Strip sentence punctuation mistaken as part of the token (. is in the class).
        wl = m.group(0).lower().rstrip(".,;:!?")
        if wl in _SUMMARY_LEXICON_ALLOW:
            continue
        if wl in cl:
            continue
        return False
    return True


def _default_resume_summary_fallback(resume_data: Optional[dict], corpus: str) -> str:
    title = _primary_job_title_from_resume(resume_data) if resume_data else ""
    if not title:
        title = "Professional"
    cl = (corpus or "").lower()
    tech = sorted(_tech_hits(corpus))
    if len(tech) >= 3:
        return _trim_redundant_words(
            f"{title} with experience in {tech[0]}, {tech[1]}, and {tech[2]}."
        )
    if len(tech) == 2:
        return _trim_redundant_words(
            f"{title} with experience in {tech[0]} and {tech[1]}, with structured delivery."
        )
    if len(tech) == 1:
        return _trim_redundant_words(
            f"{title} with experience applying {tech[0]} in professional delivery settings."
        )
    if any(x in cl for x in ("analyst", "business analyst", "systems analyst")):
        return (
            f"{title} with experience in data analysis, system validation, and cross-functional collaboration."
        )
    return _trim_redundant_words(
        f"{title} with experience in analysis, delivery, and documentation in professional settings."
    )


def _enforce_summary_resume_only(
    summary: str, corpus: str, resume_data: Optional[dict]
) -> str:
    t = (summary or "").strip()
    cl = (corpus or "").lower()
    if not t:
        return _default_resume_summary_fallback(resume_data, corpus)
    if (
        _summary_has_forbidden_jd_copy_patterns(t)
        or _summary_input_has_jd_pollution(t)
        or not _summary_words_grounded_in_resume(t, cl)
    ):
        return _default_resume_summary_fallback(resume_data, corpus)
    return t


def _resume_highlight_phrases(
    corpus: str, corpus_lower: str, resume_data: Optional[dict]
) -> List[str]:
    out: List[str] = []
    seen: Set[str] = set()
    for ph in sorted(_tech_hits(corpus)):
        key = ph.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(ph if ph != "sql" else "SQL")
        if len(out) >= 5:
            break
    if isinstance(resume_data, dict):
        sections = resume_data.get("sections")
        if isinstance(sections, dict):
            skills = sections.get("skills") or []
            if isinstance(skills, list):
                for s in skills:
                    st = str(s).strip()
                    if len(st) < 3 or len(st) > 48:
                        continue
                    sl = st.lower()
                    if sl in seen or sl not in corpus_lower:
                        continue
                    seen.add(sl)
                    out.append(st)
                    if len(out) >= 6:
                        break
    return out[:6]


def _mapping_touch_counts(eid: str, mapping_result: dict, job_signals: dict) -> Tuple[int, int, int]:
    """must_have hits, strong hits, weak hits for an evidence id (mirrors output_builder logic)."""
    must_n = strong_n = weak_n = 0
    for row in mapping_result.get("requirement_matches") or []:
        if not isinstance(row, dict) or row.get("classification") == "missing":
            continue
        rt = str(row.get("requirement_text") or "").strip()
        if not requirement_allowed_in_pipeline(rt, job_signals):
            continue
        hit = False
        for ev in row.get("matched_evidence") or []:
            if isinstance(ev, dict) and str(ev.get("id") or "") == eid:
                hit = True
                break
        if not hit:
            continue
        if str(row.get("priority") or "") == "must_have":
            must_n += 1
        if row.get("classification") == "strong":
            strong_n += 1
        elif row.get("classification") == "weak":
            weak_n += 1
    return (must_n, strong_n, weak_n)


def _global_mapping_fit(mapping_result: dict, job_signals: dict) -> Tuple[int, int, int]:
    """Counts of strong / weak / missing requirement rows."""
    strong = weak = missing = 0
    for row in mapping_result.get("requirement_matches") or []:
        if not isinstance(row, dict):
            continue
        rt = str(row.get("requirement_text") or "").strip()
        if not requirement_allowed_in_pipeline(rt, job_signals):
            continue
        c = row.get("classification")
        if c == "strong":
            strong += 1
        elif c == "weak":
            weak += 1
        elif c == "missing":
            missing += 1
    return strong, weak, missing


def _is_poor_or_sparse_fit(mapping_result: dict, job_signals: dict) -> bool:
    """Limited demonstrated overlap — prefer resume-grounded summary and more suggestions, not flattering JD copy."""
    s, w, m = _global_mapping_fit(mapping_result, job_signals)
    if s == 0:
        return True
    if s <= 1 and m >= 6:
        return True
    if s <= 2 and m >= 10:
        return True
    return False


def _low_demonstrated_fit(mapping_result: dict, job_signals: dict) -> bool:
    """Poor or medium-weak overlap — prioritize suggestion-mode bullets without claiming strong fit."""
    if _is_poor_or_sparse_fit(mapping_result, job_signals):
        return True
    s, w, m = _global_mapping_fit(mapping_result, job_signals)
    return s <= 2 and m >= 4


def _honest_unchanged_reason(must_t: int, strong_t: int, weak_t: int) -> str:
    v = (must_t + strong_t * 2 + weak_t + 7) % 3
    opts = (
        "Kept as-is; no safer rewrite improved this line.",
        "Left unchanged; this line already reads clearly enough for this role.",
        "No rewrite applied; stronger improvement would require details you’d need to verify.",
    )
    return opts[v]


def _resume_grounded_poor_fit_summary(
    corpus: str,
    corpus_lower: str,
    resume_data: Optional[dict],
) -> str:
    """
    One sentence from resume text, skills, and title only — never job description or requirements.
    """
    role = _role_label_for_summary({}, corpus_lower, [], resume_data)
    dom = _domain_settings_phrase({}, corpus_lower)
    hl = _resume_highlight_phrases(corpus, corpus_lower, resume_data)
    tech = sorted(_tech_hits(corpus))[:3]
    if len(hl) >= 3:
        s1 = f"{role} with experience in {hl[0]}, {hl[1]}, and {hl[2]}."
    elif len(hl) == 2:
        s1 = f"{role} with experience in {hl[0]} and {hl[1]}, with validation and reporting work."
    elif len(hl) == 1:
        s1 = f"{role} with experience applying {hl[0]} in professional delivery settings."
    elif len(tech) >= 2:
        s1 = (
            f"{role} with hands-on experience using {tech[0]} and {tech[1]}, "
            f"with reporting support and structured delivery in {dom} settings."
        )
    else:
        s1 = (
            f"{role} with hands-on experience in analysis, reporting, and delivery work in {dom} settings."
        )
    return _trim_redundant_words(_strip_bad_summary_phrases(s1))


def _short_theme_phrase(theme: str, max_words: int = 9) -> str:
    """Keep summary themes readable — avoid three long bullets pasted into one sentence."""
    t = re.sub(r"\s+", " ", (theme or "").strip()).strip(",;")
    if not t:
        return ""
    words = t.split()
    if len(words) > max_words:
        t = " ".join(words[:max_words]).rstrip(",;") + "…"
    return t


def _structured_themes_from_strong_requirements(
    mapping_result: dict, limit: int = 3, job_signals: Optional[dict] = None
) -> List[str]:
    """Themes from strongest matched requirement lines only — not resume bullet fragments."""
    out: List[str] = []
    seen: Set[str] = set()
    for row in mapping_result.get("requirement_matches") or []:
        if not isinstance(row, dict) or row.get("classification") != "strong":
            continue
        rt = str(row.get("requirement_text") or "").strip()
        if len(rt) < 10:
            continue
        if not _requirement_text_in_validated_set(rt, job_signals):
            continue
        if (
            is_philosophy_like_line(rt)
            or is_heading_like_line(rt)
            or is_marketing_or_manifesto_line(rt)
        ):
            continue
        if is_benefits_line(rt) or is_company_about_line(rt) or is_manifesto_or_values_line(rt):
            continue
        if not is_requirement_grade_candidate(rt):
            continue
        short = _short_req_theme(rt, 88)
        words = short.split()
        if len(words) > 10:
            short = " ".join(words[:10]).rstrip(",;") + "…"
        key = short.lower()[:72]
        if key in seen:
            continue
        seen.add(key)
        out.append(short)
        if len(out) >= limit:
            break
    return out


def _primary_job_title_from_resume(resume_data: Optional[dict]) -> str:
    """
    Strongest structured experience title for identity/summary (recent roles first).

    Prefer the longest suitable title among the first few blocks so compound lines
    (e.g. ``Senior … / … Lead``) beat a shorter first-row title when both exist.
    """
    if not isinstance(resume_data, dict):
        return ""
    sections = resume_data.get("sections")
    if not isinstance(sections, dict):
        return ""
    exp = sections.get("experience") or []
    if not isinstance(exp, list) or not exp:
        return ""
    candidates: List[str] = []
    for block in exp[:4]:
        if not isinstance(block, dict):
            continue
        t = str(block.get("title") or block.get("role") or "").strip()
        if 3 <= len(t) <= 120:
            candidates.append(t)
    if not candidates:
        return ""
    preferred = [t for t in candidates if 8 <= len(t) <= 120]
    pool = preferred if preferred else candidates
    return max(pool, key=len)


_DOMAIN_LABEL_PRETTY: Dict[str, str] = {
    "testing_uat": "UAT and testing",
    "reporting_bi": "reporting and analytics",
    "sql_data": "SQL and data validation",
    "healthcare_gov": "healthcare and government programs",
    "crm_ops": "CRM and case operations",
    "ba_stakeholder": "business analysis and stakeholder work",
}


def _domain_phrases_from_mapping(
    mapping_result: dict, limit: int = 2, job_signals: Optional[dict] = None
) -> List[str]:
    """Readable practice areas from strong matches (score_breakdown), no fabrication."""
    out: List[str] = []
    seen: Set[str] = set()
    for row in mapping_result.get("requirement_matches") or []:
        if not isinstance(row, dict) or row.get("classification") != "strong":
            continue
        rt_chk = str(row.get("requirement_text") or "").strip()
        if not _requirement_text_in_validated_set(rt_chk, job_signals):
            continue
        bd = row.get("score_breakdown") or {}
        for lab in bd.get("matched_domain_labels") or []:
            pretty = _DOMAIN_LABEL_PRETTY.get(str(lab))
            if not pretty:
                continue
            pl = pretty.lower()
            if pl in seen:
                continue
            seen.add(pl)
            out.append(pretty)
            if len(out) >= limit:
                return out
    return out


def _infer_role_label(corpus_lower: str, themes: Sequence[str]) -> str:
    """Short role label from resume-evidenced themes only (never job posting labels)."""
    blob = " ".join(themes).lower()
    if any(x in blob for x in ("uat", "test", "qa", "defect")):
        return "Quality and testing professional"
    if any(x in blob for x in ("report", "dashboard", "sql", "data")):
        return "Analyst"
    if any(x in blob for x in ("stakeholder", "business", "requirements", "facilitat")):
        return "Business professional"
    return "Professional"


def _role_label_for_summary(
    job_signals: dict,
    corpus_lower: str,
    themes: Sequence[str],
    resume_data: Optional[dict],
) -> str:
    """Prefer actual job title from resume when it clearly appears in the corpus."""
    title = _primary_job_title_from_resume(resume_data)
    if title:
        tl = title.lower()
        if tl in corpus_lower or any(
            part in corpus_lower for part in re.split(r"[\s/]+", tl) if len(part) > 5
        ):
            return title
    return _infer_role_label(corpus_lower, themes)


def _work_type_phrase(keywords: Sequence[str], corpus_lower: str) -> str:
    del keywords
    return _work_type_phrase_from_corpus(corpus_lower)


def _work_type_phrase_from_corpus(corpus_lower: str) -> str:
    cl = corpus_lower or ""
    if "report" in cl or "dashboard" in cl or "sql" in cl:
        return "analysis, reporting, and delivery"
    if "test" in cl or "uat" in cl or "qa" in cl:
        return "validation and delivery"
    if "stakeholder" in cl or "business" in cl:
        return "stakeholder-facing analysis and delivery"
    return "analysis and delivery"


def _domain_settings_phrase(job_signals: dict, corpus_lower: str) -> str:
    for phrase in (
        "healthcare",
        "medicaid",
        "hipaa",
        "clinical",
        "government",
        "public sector",
        "federal",
    ):
        if phrase in corpus_lower:
            return "healthcare and government"
    if "finance" in corpus_lower or "banking" in corpus_lower:
        return "financial services"
    if "retail" in corpus_lower:
        return "retail"
    return "team and stakeholder"


def _filter_keywords_for_summary(keywords: Sequence[str], corpus_lower: str) -> List[str]:
    """JD keywords that appear in resume text, excluding theme-stop garbage."""
    out: List[str] = []
    seen: Set[str] = set()
    for k in keywords:
        ks = str(k).strip()
        if not ks or len(ks) < 3:
            continue
        kl = ks.lower()
        if kl in _SUMMARY_THEME_STOP or kl in _SUMMARY_KEYWORD_SKIP:
            continue
        if kl not in corpus_lower:
            continue
        if kl in seen:
            continue
        seen.add(kl)
        out.append(ks)
        if len(out) >= 6:
            break
    return out


def _tokenize_lower(text: str) -> List[str]:
    return re.findall(r"[A-Za-z][A-Za-z0-9+#.\-]{1,}", (text or "").lower())


def _tech_hits(text: str) -> Set[str]:
    """Return which known tech phrases appear in text (lowercase canonical hits)."""
    tl = (text or "").lower()
    found: Set[str] = set()
    for phrase in _KNOWN_TECH_PHRASES:
        if len(phrase) <= 3:
            if re.search(rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])", tl):
                found.add(phrase)
        elif phrase in tl:
            found.add(phrase)
    return found


def _numeric_tokens(text: str) -> Set[str]:
    return {m.group(0).lower().replace(",", "") for m in _NUMERIC_PATTERN.finditer(text or "")}


def _new_ownership_claims(before: str, after: str, corpus: Optional[str] = None) -> bool:
    """True if after adds ownership language not already in before or corpus."""
    tb = set(_tokenize_lower(before))
    ta = set(_tokenize_lower(after))
    tc = set(_tokenize_lower(corpus or ""))
    new_s = (ta & _STRONG_OWNERSHIP_WORDS) - (tb & _STRONG_OWNERSHIP_WORDS) - (tc & _STRONG_OWNERSHIP_WORDS)
    return bool(new_s)


def _grounded_rewrite_ok(
    before: str, after: str, *, corpus: Optional[str] = None
) -> Tuple[bool, str]:
    """
    Lightweight guardrails. For bullets, `corpus` is omitted (strict: original text only).
    For summaries, pass full resume corpus so themes already evidenced can appear.
    """
    b, a = (before or "").strip(), (after or "").strip()
    if not a:
        return False, "empty rewrite"
    nums_b, nums_a = _numeric_tokens(b), _numeric_tokens(a)
    nums_c = _numeric_tokens(corpus or "")
    new_nums = nums_a - nums_b - nums_c
    if new_nums:
        return False, f"introduces new numeric tokens: {sorted(new_nums)[:5]}"

    tech_b, tech_a = _tech_hits(b), _tech_hits(a)
    tech_c = _tech_hits(corpus or "")
    new_tech = tech_a - tech_b - tech_c
    if new_tech:
        return False, f"introduces technologies not grounded in prior text: {sorted(new_tech)}"

    if _new_ownership_claims(b, a, corpus if corpus else None):
        return False, "introduces stronger ownership or leadership claims than grounded text allows"

    return True, ""


def _bullet_fact_check(before: str, after: str) -> Tuple[bool, str]:
    """Strict bullet check: no new facts vs original bullet only."""
    b, a = (before or "").strip(), (after or "").strip()
    if not a:
        return False, "empty rewrite"
    if len(b) > 0 and len(a) > max(550, len(b) * 4 + 120):
        return False, "rewrite length implausible vs original"
    return _grounded_rewrite_ok(before, after, corpus=None)


def _strip_bullet_lead(s: str) -> str:
    return re.sub(r"^[\s\-–•*]+", "", (s or "").strip())


def _readability_score(text: str) -> float:
    """Rough score: moderate length, few comma-splices, has a verb-like token."""
    t = (text or "").strip()
    if not t:
        return 0.0
    words = max(len(t.split()), 1)
    comma_pen = (t.count(",") + t.count(";")) / max(words / 12.0, 1.0)
    verb_bonus = 0.45 if _COMMON_VERBS_RE.search(t) else 0.0
    return min(words / 22.0, 2.5) - comma_pen + verb_bonus


def _bullet_readability_ok(before: str, after: str) -> Tuple[bool, str]:
    """Deterministic readability guard for rewritten bullets — conservative: when unsure, reject."""
    a = _strip_bullet_lead(after or "")
    b = _strip_bullet_lead(before or "")
    if not a:
        return False, "empty"
    first = a[0]
    if first.isalpha() and not first.isupper():
        bf0 = b[0] if b else ""
        if bf0.isalpha() and bf0.isupper():
            return False, "does not start with a capital letter"
    if first.isdigit():
        # Allow numbered lead-ins if a verb appears later
        if _COMMON_VERBS_RE.search(a) is None:
            return False, "no verb-like token after numeric lead-in"
    elif _COMMON_VERBS_RE.search(a) is None:
        return False, "no clear verb (reads like a fragment)"

    if a.count(",") >= 4 and len(a) < 220:
        parts = [p.strip() for p in a.split(",")]
        if sum(1 for p in parts if len(p) < 14) >= 3:
            return False, "comma-heavy fragments"

    ca, cb = a.count(","), b.count(",")
    if ca > cb + 1:
        return False, "more comma splices than original"
    if a.count(";") > b.count(";"):
        return False, "added semicolon fragments"
    if len(a) <= max(len(b), 1) * 1.12 and ca > cb:
        return False, "comma structure degraded without added substance"

    # Suspicious reorder: same long words but first content word was tail of original
    a_words = [w for w in re.findall(r"[A-Za-z]{4,}", a.lower())]
    b_words = [w for w in re.findall(r"[A-Za-z]{4,}", b.lower())]
    if len(a_words) >= 5 and len(b_words) >= 5 and set(a_words) == set(b_words) and a.lower() != b.lower():
        if a_words[0] == b_words[-1] and a_words[0] not in b_words[:3]:
            return False, "awkward phrase reorder"

    # Same word multiset with lead anchor pushed past midpoint — clause shuffle, not a real edit.
    b_tok = _tokenize_lower(b)
    a_tok = _tokenize_lower(a)
    if len(b_tok) >= 10 and sorted(b_tok) == sorted(a_tok):

        def _first_content_idx(tokens: List[str]) -> Optional[int]:
            for i, w in enumerate(tokens):
                if len(w) > 3 and w not in _READ_STOP:
                    return i
            return None

        bi = _first_content_idx(b_tok)
        if bi is not None and bi < max(1, len(b_tok) // 4):
            anchor = b_tok[bi]
            if anchor in a_tok:
                ai = a_tok.index(anchor)
                if ai > len(a_tok) // 2:
                    return False, "opening clause moved (likely shuffle)"

    if len(b) > 80:
        ap = [p.strip() for p in a.split(",")]
        bp = [p.strip() for p in b.split(",")]
        if len(ap) > len(bp) + 2:
            return False, "clause soup vs original"

    ra, rb = _readability_score(a), _readability_score(b)
    if ra < rb - 0.1:
        return False, "not clearly better than original"
    if rb > 0.35 and ra + 0.25 < rb:
        return False, "reads less clearly than the original"

    return True, ""


def _bullet_rewrite_acceptable(before: str, after: str) -> Tuple[bool, str]:
    ok, r = _bullet_fact_check(before, after)
    if not ok:
        return False, r
    ok2, r2 = _bullet_readability_ok(before, after)
    if not ok2:
        return False, r2
    return True, ""


def _meaningful_bullet_rewrite(before: str, after: str) -> bool:
    """True only when rewrite changes substance, not just spacing or harmless reorder of the same tokens."""
    b, a = (before or "").strip(), (after or "").strip()
    if not b or not a:
        return False
    if b == a:
        return False
    alnum_b = re.sub(r"[^\w\s]", "", re.sub(r"\s+", " ", b).lower())
    alnum_a = re.sub(r"[^\w\s]", "", re.sub(r"\s+", " ", a).lower())
    if alnum_b == alnum_a:
        return False
    tb, ta = set(_tokenize_lower(b)), set(_tokenize_lower(a))
    if tb == ta and abs(len(a.split()) - len(b.split())) <= 3:
        return False
    return True


def _has_strong_requirement_match(mapping_result: dict, job_signals: dict) -> bool:
    for row in mapping_result.get("requirement_matches") or []:
        if not isinstance(row, dict) or row.get("classification") != "strong":
            continue
        rt = str(row.get("requirement_text") or "").strip()
        if requirement_allowed_in_pipeline(rt, job_signals):
            return True
    return False


def _bullet_text_in_resume(resume_data: dict, bullet_text: str) -> bool:
    """Mapper output must reference text that still exists on the resume (anti-stale targets)."""
    bt = " ".join(str(bullet_text).split()).strip().lower()
    if len(bt) < 4:
        return False
    corpus = _corpus_from_resume(resume_data).lower()
    if bt in corpus:
        return True
    if len(bt) >= 24:
        head = bt[:80]
        if head in corpus:
            return True
    return False


def _corpus_from_resume(resume_data: dict) -> str:
    """All resume text for honest keyword / evidence surfacing."""
    parts: List[str] = []
    raw = resume_data.get("raw_text") or ""
    if raw:
        parts.append(raw)
    summ = resume_data.get("summary") or ""
    if summ:
        parts.append(summ)
    sections = resume_data.get("sections")
    if isinstance(sections, dict):
        for key in ("summary", "experience", "skills", "education", "certifications", "projects"):
            block = sections.get(key)
            if isinstance(block, list):
                for item in block:
                    if isinstance(item, str):
                        parts.append(item)
                    elif isinstance(item, dict):
                        for k in ("company", "title", "date_range"):
                            if item.get(k):
                                parts.append(str(item[k]))
                        for bu in item.get("bullets") or []:
                            parts.append(str(bu))
            elif isinstance(block, str):
                parts.append(block)
    return normalize_whitespace(" ".join(parts))


def _current_summary_text(resume_data: dict) -> str:
    sections = resume_data.get("sections")
    if isinstance(sections, dict):
        summ = sections.get("summary") or []
        if isinstance(summ, list) and summ:
            return normalize_whitespace(" ".join(str(s) for s in summ if str(s).strip()))
    s = (resume_data.get("summary") or "").strip()
    if s:
        return s
    corpus = _corpus_from_resume(resume_data)
    if corpus:
        return corpus.split("\n")[0].strip()[:800]
    return ""


def _summary_seed_from_resume(resume_data: dict, corpus: str, max_chars: int = 400) -> str:
    """Seed LLM/deterministic summary from resume summary or first resume line only — never JD/requirements."""
    if not isinstance(resume_data, dict):
        return ""
    sections = resume_data.get("sections")
    if isinstance(sections, dict):
        summ = sections.get("summary") or []
        if isinstance(summ, list) and summ:
            t0 = str(summ[0]).strip()
            if len(t0) >= 20:
                seed = _trim_redundant_words(t0)
                return seed[: max_chars - 1].rstrip() + "…" if len(seed) > max_chars else seed
    raw = (resume_data.get("summary") or "").strip()
    if len(raw) >= 20:
        seed = _trim_redundant_words(raw)
        return seed[: max_chars - 1].rstrip() + "…" if len(seed) > max_chars else seed
    first = (corpus or "").split("\n")[0].strip() if corpus else ""
    if len(first) >= 24:
        return first[: max_chars - 1].rstrip() + "…" if len(first) > max_chars else first
    return ""


def _trim_redundant_words(text: str) -> str:
    t = re.sub(r"\s+", " ", (text or "").strip())
    t = re.sub(r"\s+([.,;])", r"\1", t)
    return t


def _strip_bad_summary_phrases(text: str) -> str:
    """Remove meta / keyword-list framing from summary text."""
    s = (text or "").strip()
    if not s:
        return s
    s = _SUMMARY_META_BAD.sub("", s)
    s = re.sub(r"\s+,", ",", s)
    s = re.sub(r",?\s*include\s*:?\s*$", "", s, flags=re.I)
    s = re.sub(r"\s{2,}", " ", s).strip()
    return s


def _summary_prose_ok(text: str) -> bool:
    """Reject keyword dumps and meta phrasing."""
    t = _strip_bad_summary_phrases(text or "")
    if len(t) < 28:
        return False
    if _SUMMARY_META_BAD.search(t):
        return False
    tl = t.lower()
    if tl.count(",") >= 4 and len(t) < 220:
        return False
    if "include " in tl and t.count(",") >= 3:
        return False
    if _COMMON_VERBS_RE.search(t) is None:
        return False
    return True


def _summary_hard_validate(text: str) -> Tuple[bool, str]:
    """Reject contact info, mashups, and non-summary shapes (deterministic)."""
    t = _strip_bad_summary_phrases(text or "").strip()
    if not t:
        return False, "empty"
    if len(t) > 520:
        return False, "too long"
    if _SUMMARY_EMAIL.search(t) or _SUMMARY_PHONE.search(t) or _SUMMARY_URL.search(t):
        return False, "contact or link pattern"
    if _SUMMARY_META_EXTRA.search(t):
        return False, "meta or reference phrasing"
    if _SUMMARY_BENEFITS_OR_OFFER.search(t):
        return False, "benefits or offer phrasing"
    if _summary_input_has_jd_pollution(t):
        return False, "benefits, employer marketing, or manifesto phrasing"
    if re.search(r"\bbackground\s+aligns\s+with\b", t, re.I):
        return False, "JD alignment boilerplate"
    lead = t.lstrip()
    if lead and lead[0].isalpha() and not lead[0].isupper():
        return False, "starts with lowercase"
    if lead and lead[0] in ",.;:)]}":
        return False, "starts mid-sentence"
    parts = re.split(r"(?<=[.!?])\s+", t)
    parts = [p for p in parts if p.strip()]
    if len(parts) > 2:
        return False, "more than two sentences"
    if t.count(";") >= 3:
        return False, "fragment pile"
    if t.count(",") >= 5 and len(t) < 340:
        return False, "comma-spliced clause pile"
    if t.count(",") >= 4:
        chunks = [c.strip() for c in t.split(",")]
        if len(chunks) >= 5 and sum(1 for c in chunks if len(c.split()) <= 5) >= 4:
            return False, "list-like without sentence structure"
    tech_only = len(_tech_hits(t)) >= 4 and t.count(".") == 0 and t.count(",") >= 3
    if tech_only:
        return False, "reads like a tool list"
    tl = t.lower()
    if re.search(
        r"\b(pmp|cpa|cissp|comptia|cfa|certified\s+scrum|scrum\s+master|aws\s+certified|"
        r"gcp\s+professional|lean\s+six\s+sigma|professional\s+certificate)\b",
        tl,
    ):
        return False, "certification or credential list"
    if tl.count("certified") + tl.count("certification") >= 2:
        return False, "certification-heavy"
    return True, ""


def _summary_acceptable_for_output(text: str) -> bool:
    if not _summary_prose_ok(text):
        return False
    ok, _ = _summary_hard_validate(text)
    return ok


def _gather_requirements_for_evidence(
    mapping_result: dict, evidence_id: str, job_signals: Optional[dict] = None
) -> List[Dict[str, Any]]:
    """Must-have / preferred rows whose matched_evidence includes this id."""
    out: List[Dict[str, Any]] = []
    eid = str(evidence_id)
    for row in mapping_result.get("requirement_matches") or []:
        if not isinstance(row, dict):
            continue
        if row.get("classification") == "missing":
            continue
        rt = str(row.get("requirement_text") or "").strip()
        if not _requirement_text_in_validated_set(rt, job_signals):
            continue
        for ev in row.get("matched_evidence") or []:
            if isinstance(ev, dict) and str(ev.get("id")) == eid:
                out.append(
                    {
                        "requirement_id": row.get("requirement_id"),
                        "requirement_text": row.get("requirement_text"),
                        "priority": row.get("priority"),
                        "classification": row.get("classification"),
                        "notes": row.get("notes"),
                    }
                )
                break
    return out


def _build_rewrite_packet(
    resume_data: dict,
    mapping_result: dict,
    job_signals: dict,
    targets: List[dict],
    summary_for_prompt: str,
) -> Dict[str, Any]:
    bullets_packet: List[Dict[str, Any]] = []
    for t in targets:
        if not isinstance(t, dict):
            continue
        eid = str(t.get("evidence_id") or "").strip()
        if not eid:
            continue
        reqs = _gather_requirements_for_evidence(mapping_result, eid, job_signals)
        bullets_packet.append(
            {
                "evidence_id": eid,
                "section": t.get("section"),
                "company": t.get("company"),
                "original_bullet": str(t.get("text") or "").strip(),
                "mapper_reason": t.get("reason"),
                "linked_requirements": reqs,
            }
        )

    return {
        "summary_before": summary_for_prompt,
        "resume_corpus_excerpt": _corpus_from_resume(resume_data)[:4000],
        "job_keywords": [],
        "role_focus": [],
        "must_have_requirements": [],
        "preferred_requirements": [],
        "rewrite_target_bullets": bullets_packet,
    }


def _strip_json_fence(raw: str) -> str:
    t = raw.strip()
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", t, re.I)
    if m:
        return m.group(1).strip()
    return t


def _safe_parse_llm_json(raw: str) -> Optional[Dict[str, Any]]:
    """Parse LLM JSON only via json.loads / raw_decode — no greedy brace slicing."""
    if not raw:
        return None
    text = _strip_json_fence(raw).strip()
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        pass
    dec = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch != "{":
            continue
        try:
            obj, _ = dec.raw_decode(text, i)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            continue
    return None


def _openai_chat_completion(
    system_prompt: str,
    user_content: str,
    *,
    model: Optional[str] = None,
    timeout_s: float = 60.0,
) -> Optional[str]:
    key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    if not key:
        return None
    mdl = model or os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    body = json.dumps(
        {
            "model": mdl,
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None
    try:
        return payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return None


_SYSTEM_PROMPT = """You are a conservative resume editor. You output ONLY valid JSON (no markdown).

You will receive a JSON packet with:
- summary_before: current summary text (must be the basis for summary_after)
- resume_corpus_excerpt: full resume text for grounding
- rewrite_target_bullets: bullets to rewrite, each with original_bullet and linked_requirements
Job posting text is NOT included. summary_after must use ONLY words and facts supported by summary_before and resume_corpus_excerpt.

Your JSON response MUST have exactly this shape:
{
  "summary_after": "<string>",
  "summary_why": "<one short sentence>",
  "bullets": [
    {
      "evidence_id": "<same id as input>",
      "after": "<rewritten bullet>",
      "why": "<short reason>"
    }
  ]
}

Rules (violations mean you should keep text close to the original):
- Preserve facts: employers, dates, products, and responsibilities must stay true to original_bullet and resume_corpus_excerpt.
- Do NOT invent metrics, percentages, dollar amounts, timelines, or counts not present in original_bullet or resume_corpus_excerpt.
- Do NOT add tools, languages, vendors, or platforms not already mentioned in original_bullet (or clearly named in resume_corpus_excerpt for the same role).
- Do NOT upgrade "supported/participated" into "led/owned/directed" unless original_bullet already shows that level of ownership.
- Do NOT claim gaps as strengths. If evidence is thin, make minimal clarity edits only.
- For bullets only: improve clarity using linked_requirements and honest wording grounded in original_bullet and resume_corpus_excerpt.
- summary_after: write 1–2 complete professional sentences (prose), like a real resume summary — not a keyword list, not meta text ("related terms", "keywords include"), and not invented tools or metrics.
- Include one entry in bullets for EVERY evidence_id provided; keep evidence_id values identical.
"""


def _deterministic_summary(
    summary_before: str,
    corpus_lower: str,
    job_keywords: Sequence[str],
    *,
    has_strong_requirement_match: bool,
) -> Tuple[str, str]:
    """
    One–two sentence professional summary from existing wording only (no keyword appendix).
    """
    del corpus_lower, job_keywords
    merged = _trim_redundant_words(summary_before)
    merged = _strip_bad_summary_phrases(merged)
    parts = re.split(r"(?<=[.!?])\s+", merged)
    sentences = [p.strip() for p in parts if p.strip()]
    if not sentences and summary_before.strip():
        sentences = [summary_before.strip()[:800]]
    out = " ".join(sentences[:2]) if sentences else ""
    out = _trim_redundant_words(_strip_bad_summary_phrases(out))
    if len(out) > 900:
        out = out[:897].rsplit(" ", 1)[0] + "."
    if not _summary_prose_ok(out) and summary_before.strip():
        fb = _strip_bad_summary_phrases(summary_before.strip())
        parts2 = re.split(r"(?<=[.!?])\s+", fb)
        sentences2 = [p.strip() for p in parts2 if p.strip()]
        out = " ".join(sentences2[:2]) if sentences2 else fb
        out = _trim_redundant_words(out[:900])
    if not out.strip():
        out = "Professional background as shown in the resume; see experience for role-specific detail."
    why = (
        "Short professional sentences grounded in your existing summary — no keyword lists or new tools."
        if has_strong_requirement_match
        else "Conservative sentences from your existing summary — no invented metrics or keyword-style lists."
    )
    return out, why


def _deterministic_bullet(before: str, job_keywords: Sequence[str]) -> Tuple[str, str]:
    del job_keywords
    after = _trim_redundant_words(before)
    b_norm = re.sub(r"\s+", " ", (before or "").strip())
    a_norm = re.sub(r"\s+", " ", (after or "").strip())
    if b_norm == a_norm:
        why = "Reviewed for clarity; no edit applied — text already matched after normalizing spaces."
    else:
        why = (
            "Same facts; adjusted spacing and punctuation only so the line reads faster "
            "(original clause order kept)."
        )
    return after, why


_OUTCOME_HINT = re.compile(
    r"\b(impact|outcome|result|reduced|increased|improved|saved|accuracy|efficien|reliabil|quality|timeliness)\b",
    re.I,
)
_WEAK_OPENING = re.compile(
    r"^(?:worked|helped|assisted|supported|involved|participated)\b",
    re.I,
)


def _short_req_theme(text: str, max_len: int = 56) -> str:
    t = re.sub(r"\s+", " ", (text or "").strip())
    if len(t) <= max_len:
        return t
    return t[: max_len - 1].rsplit(" ", 1)[0].rstrip() + "…"


def _bullet_improvement_suggestions(
    evidence_id: str,
    before: str,
    mapping_result: dict,
    job_signals: dict,
    corpus_lower: str,
) -> List[str]:
    """
    At most 2 specific, grounded suggestions when rewrite did not change text.
    """
    out: List[str] = []
    seen: Set[str] = set()
    bt = (before or "").strip()
    btl = bt.lower()

    def add(s: str) -> None:
        s = s.strip()
        if not s or s.lower() in seen:
            return
        seen.add(s.lower())
        out.append(s)

    linked = _gather_requirements_for_evidence(mapping_result, evidence_id, job_signals)
    pick = None
    for x in linked:
        if str(x.get("priority") or "") == "must_have":
            pick = x
            break
    if pick is None and linked:
        pick = linked[0]
    req_text = str(pick.get("requirement_text") or "").strip() if pick else ""
    req_l = req_text.lower()

    tools_here = sorted(_tech_hits(bt))
    if ("sql" in btl or "sql" in tools_here or "query" in btl) and len(out) < 2:
        add(
            "If this work involved SQL or validation, name the report, table, or dataset family you touched—only if that detail appears elsewhere on your resume."
        )
    if any(k in btl for k in ("uat", "defect", "qa", "test ", "testing")) or any(
        k in req_l for k in ("uat", "defect", "acceptance", "triage", "test")
    ):
        add(
            "If you coordinated defect triage or UAT across teams, name who you partnered with (QA, business, vendor)—only when that is accurate."
        )
    if any(k in btl for k in ("report", "dashboard", "power bi", "tableau", "bi")) or any(
        k in req_l for k in ("reporting", "dashboard", "business intelligence")
    ):
        add(
            "If this improved reporting accuracy or workflow reliability, state that outcome in plain language you can support without new metrics."
        )
    if any(
        k in btl or k in req_l
        for k in (
            "medicaid",
            "medicare",
            "hipaa",
            "healthcare",
            "clinical",
            "cms",
        )
    ):
        add(
            "If this work touched Medicaid, CMS, or plan rules, name the program or intake context you supported—only where that is already on your resume."
        )
    if any(k in btl or k in req_l for k in ("crm", "dynamics", "case management", "salesforce")):
        add(
            "If this bullet reflects CRM or case-management work, name the workflow (case type, intake, closure) you handled—without adding systems not already listed."
        )
    if req_text and len(out) < 2 and not is_marketing_or_manifesto_line(req_text):
        rs = _short_req_theme(req_text, 44)
        if rs:
            add(
                f"If this bullet supports “{rs}”, spell out the tool, workflow, or stakeholder handoff you owned for that thread."
            )
    if tools_here and len(out) < 2:
        t = tools_here[0]
        add(
            f"If {t} was central here, say what you produced with it (artifact, integration, or validation step)—without adding tools not already on your resume."
        )
    if len(out) < 2 and _WEAK_OPENING.search(bt) and req_text and not is_marketing_or_manifesto_line(req_text):
        rs = _short_req_theme(req_text, 40)
        if rs:
            add(
                f'If you owned work matching "{rs}," lead with the verb you use elsewhere '
                "for that same level of ownership—only if that matches the facts."
            )

    if len(out) < 2 and _is_poor_or_sparse_fit(mapping_result, job_signals):
        add(
            "If this work supported a report, dashboard, or workflow, name that output directly."
        )
    if len(out) < 2 and _is_poor_or_sparse_fit(mapping_result, job_signals):
        add(
            "If you coordinated across teams, name the partner groups when that is accurate."
        )

    return out[:2]


def _last_resort_grounded_suggestion(before: str, req_text: str) -> str:
    """Single line when other heuristics miss — still tied to bullet or posting text, not generic resume advice."""
    bt = (before or "").strip()
    if req_text and not is_philosophy_like_line(req_text) and not is_marketing_or_manifesto_line(req_text):
        rs = _short_req_theme(req_text, 50)
        if rs:
            return (
                f"Add one concrete detail you can already support elsewhere on the resume (system, team, or artifact) "
                f"that ties this line to “{rs}.”"
            )
    lead = re.split(r"[.;]", bt, 1)[0].strip()
    if len(lead) >= 14:
        clip = lead[:70] + ("…" if len(lead) > 70 else "")
        return (
            f"Tighten the first clause of this line (“{clip}”) with one specific noun or scope detail "
            "already present in another bullet."
        )
    toks = re.findall(r"[A-Za-z]{4,}", bt)
    if toks:
        anchor = toks[0].lower()
        return (
            f'Where “{anchor}” is the main thread, add one scope detail you already mention elsewhere '
            "(system, team, or artifact)—without new tools or employers."
        )
    return (
        "Add one concrete scope detail (system, team, or artifact) drawn from wording you already use elsewhere on the resume."
    )


def _bullet_suggestions_with_fallback(
    evidence_id: str,
    before: str,
    mapping_result: dict,
    job_signals: dict,
    corpus_lower: str,
) -> List[str]:
    """Always try to return 1–2 grounded lines when the primary heuristics are thin."""
    base = _bullet_improvement_suggestions(
        evidence_id, before, mapping_result, job_signals, corpus_lower
    )
    if len(base) >= 1:
        return base[:2]
    linked = _gather_requirements_for_evidence(mapping_result, evidence_id, job_signals)
    req_text = ""
    for x in linked:
        if str(x.get("priority") or "") == "must_have":
            req_text = str(x.get("requirement_text") or "").strip()
            break
    if not req_text and linked:
        req_text = str(linked[0].get("requirement_text") or "").strip()
    out: List[str] = []
    if req_text and not is_philosophy_like_line(req_text) and not is_marketing_or_manifesto_line(req_text):
        rs = _short_req_theme(req_text, 52)
        if rs:
            out.append(
                f"If this line reflects “{rs},” state what you delivered or validated in one concrete phrase you can stand behind."
            )
    btl = (before or "").lower()
    if len(out) < 2 and ("sql" in btl or "query" in btl):
        out.append(
            "If this involved SQL validation or reporting, name the report, dataset, or system you touched—only if that is already credible elsewhere on the resume."
        )
    if len(out) < 2 and any(
        k in btl for k in ("team", "cross", "partner", "stakeholder", "engineering", "reporting")
    ):
        out.append(
            "If you coordinated across engineering, reporting, or business teams, say which groups you partnered with when that is accurate."
        )
    if len(out) < 2 and req_text and not is_philosophy_like_line(req_text) and not is_marketing_or_manifesto_line(
        req_text
    ):
        out.append(
            "If this improved reliability or reduced errors, state that outcome in plain language you can support without new numbers."
        )
    if len(out) < 2 and _is_poor_or_sparse_fit(mapping_result, job_signals):
        out.append(
            "If this improved accuracy, reliability, or release readiness, state that outcome explicitly if true."
        )
    if not out:
        out.append(_last_resort_grounded_suggestion(before, req_text))
    return out[:2]


def _coaching_tip_line_for_bullet(
    before: str, evidence_id: str, mapping_result: dict, job_signals: Optional[dict] = None
) -> str:
    """Single grounded line for why-field coaching when not in top suggestion quota."""
    linked = _gather_requirements_for_evidence(mapping_result, evidence_id, job_signals)
    req_text = ""
    for x in linked:
        if str(x.get("priority") or "") == "must_have":
            req_text = str(x.get("requirement_text") or "").strip()
            break
    if not req_text and linked:
        req_text = str(linked[0].get("requirement_text") or "").strip()
    return _last_resort_grounded_suggestion(before, req_text)


def _template_summary_from_signals(
    mapping_result: dict,
    job_signals: dict,
    corpus: str,
    corpus_lower: str,
    keywords: Sequence[str],
    resume_data: Optional[dict] = None,
) -> str:
    """Deterministic summary from resume corpus only — match strength only changes length, not JD sourcing."""
    del keywords
    base = _resume_grounded_poor_fit_summary(corpus, corpus_lower, resume_data)
    if _is_poor_or_sparse_fit(mapping_result, job_signals):
        return base
    wt = _work_type_phrase_from_corpus(corpus_lower)
    dom = _domain_settings_phrase({}, corpus_lower)
    s2 = f"Supports {wt} in {dom} settings."
    if _summary_words_grounded_in_resume(s2, corpus_lower):
        return _trim_redundant_words(_strip_bad_summary_phrases(f"{base} {s2}"))
    return base


def _minimal_summary_fallback(
    working_summary: str,
    corpus: str,
    keywords: Sequence[str],
    *,
    mapping_result: Optional[dict] = None,
    job_signals: Optional[dict] = None,
    resume_data: Optional[dict] = None,
) -> str:
    w = _strip_bad_summary_phrases(working_summary.strip())
    resume_polluted = _summary_input_has_jd_pollution(w)
    if not resume_polluted:
        for part in re.split(r"(?<=[.!?])\s+", w):
            p = part.strip()
            if p and _summary_input_has_jd_pollution(p):
                resume_polluted = True
                break
    if len(w) >= 40 and _COMMON_VERBS_RE.search(w) and not resume_polluted:
        parts = re.split(r"(?<=[.!?])\s+", w)
        sents = [p.strip() for p in parts if p.strip()][:2]
        if sents:
            cand = _trim_redundant_words(" ".join(sents))
            if _summary_acceptable_for_output(cand):
                return cand
    mr = mapping_result if isinstance(mapping_result, dict) else {}
    js = job_signals if isinstance(job_signals, dict) else {}
    return _template_summary_from_signals(
        mr, js, corpus, (corpus or "").lower(), keywords, resume_data=resume_data
    )


def _ensure_summary_always(
    summary_after: str,
    summary_why: str,
    working_summary: str,
    corpus: str,
    corpus_lower: str,
    mapping_result: dict,
    job_signals: dict,
    keywords: Sequence[str],
    has_strong: bool,
    resume_data: Optional[dict] = None,
) -> Tuple[str, str]:
    """Guarantee non-empty, readable 1–2 sentence professional summary."""
    t = _trim_redundant_words(_strip_bad_summary_phrases((summary_after or "").strip()))
    if t and _summary_acceptable_for_output(t):
        return t, summary_why
    # Try minimal from working text
    cand = _minimal_summary_fallback(
        working_summary,
        corpus,
        keywords,
        mapping_result=mapping_result,
        job_signals=job_signals,
        resume_data=resume_data,
    )
    cand = _trim_redundant_words(_strip_bad_summary_phrases(cand))
    if _summary_acceptable_for_output(cand):
        return cand, (
            "Summary built from your existing wording and visible evidence — no keyword lists or new claims."
        )
    built = _template_summary_from_signals(
        mapping_result, job_signals, corpus, corpus_lower, keywords, resume_data=resume_data
    )
    built = _trim_redundant_words(_strip_bad_summary_phrases(built))
    if not _summary_acceptable_for_output(built):
        built = (
            f"{_role_label_for_summary(job_signals, corpus_lower, [], resume_data)} "
            f"with experience in analysis, delivery, and documentation in professional settings."
        )
    if _is_poor_or_sparse_fit(mapping_result, job_signals):
        why = (
            "Summary kept to resume-grounded wording — posting overlap is limited; "
            "no benefits, compensation, or employer marketing lines."
        )
    elif has_strong:
        why = (
            "Summary assembled from role signals and evidence on your resume — not a keyword list; no invented metrics."
        )
    else:
        why = (
            "Summary assembled conservatively from your resume and posting signals — no invented tools or metrics."
        )
    return built, why


def _apply_llm_or_fallback(
    packet: Dict[str, Any],
    targets: List[dict],
    guardrail_notes: List[str],
) -> Tuple[Optional[str], Optional[str], Dict[str, Tuple[str, str]]]:
    """
    Returns (summary_after, summary_why, evidence_id -> (after, why)).
    LLM may be None; caller uses deterministic fill for missing parts.
    """
    user_json = json.dumps(packet, ensure_ascii=False)
    raw = _openai_chat_completion(_SYSTEM_PROMPT, user_json)
    if raw is None:
        guardrail_notes.append("LLM rewrite skipped (no API key or request failed); used deterministic edits.")
        return None, None, {}

    parsed = _safe_parse_llm_json(raw)
    if not parsed:
        guardrail_notes.append("LLM output was not valid JSON; used deterministic edits.")
        return None, None, {}

    summary_after = parsed.get("summary_after")
    summary_why = parsed.get("summary_why")
    if summary_after is not None and not isinstance(summary_after, str):
        summary_after = None
        guardrail_notes.append("LLM summary_after was not a string; ignored.")
    if summary_why is not None and not isinstance(summary_why, str):
        summary_why = None

    bullets = parsed.get("bullets")
    out: Dict[str, Tuple[str, str]] = {}
    if isinstance(bullets, list):
        for item in bullets:
            if not isinstance(item, dict):
                continue
            eid = str(item.get("evidence_id") or "").strip()
            raw_after = item.get("after")
            if not isinstance(raw_after, str):
                continue
            after = raw_after.strip()
            why = str(item.get("why") or "").strip() or (
                "Mapped to this evidence line; wording stays grounded in your resume text."
            )
            if eid and after:
                out[eid] = (after, why)

    sa = summary_after.strip() if isinstance(summary_after, str) else ""
    sw = summary_why.strip() if isinstance(summary_why, str) else ""
    return sa or None, sw or None, out


def rewrite_resume_bullets(
    resume_data: dict, mapping_result: dict, job_signals: dict
) -> dict:
    """
    Rewrite summary and only experience bullets listed in mapping_result.rewrite_targets.

    Returns a presentation-ready dict plus compatibility keys for the existing pipeline
    (tailored_summary, tailored_experience_bullets, change_items, tailored_skills).
    """
    guardrail_notes: List[str] = [
        "Only the professional summary and mapper-selected experience bullets were candidates for rewrite.",
        "Skills, education, and certifications were not modified.",
    ]

    has_strong = _has_strong_requirement_match(mapping_result, job_signals)

    summary_display_before = _current_summary_text(resume_data)
    corpus = _corpus_from_resume(resume_data)
    corpus_lower = corpus.lower()

    seed = _summary_seed_from_resume(resume_data, corpus)
    working_summary = summary_display_before.strip()
    if len(working_summary) < 20 and seed:
        working_summary = seed
        guardrail_notes.append(
            "No substantive summary was present; seeded from resume summary or first resume line only."
        )

    keywords = [str(k) for k in (job_signals.get("keywords") or []) if k][:15]

    rt_raw = mapping_result.get("rewrite_targets")
    targets: List[dict] = []
    seen_target_ids: Set[str] = set()
    if isinstance(rt_raw, list):
        for item in rt_raw:
            if not isinstance(item, dict) or not str(item.get("text") or "").strip():
                continue
            eid_key = str(item.get("evidence_id") or "").strip()
            if not eid_key:
                guardrail_notes.append("Skipped a rewrite_targets row with no evidence_id.")
                continue
            if str(item.get("section") or "") != "experience":
                continue
            if eid_key in seen_target_ids:
                guardrail_notes.append(
                    f"Duplicate rewrite_targets entry for {eid_key} was skipped (first wins)."
                )
                continue
            seen_target_ids.add(eid_key)
            targets.append(item)

    packet = _build_rewrite_packet(
        resume_data, mapping_result, job_signals, targets, summary_for_prompt=working_summary
    )

    llm_summary_after, llm_summary_why, llm_bullets = _apply_llm_or_fallback(
        packet, targets, guardrail_notes
    )

    if llm_summary_after and len(llm_summary_after) > 3000:
        guardrail_notes.append("LLM summary exceeded length cap; discarded.")
        llm_summary_after = None
        llm_summary_why = None

    poor_sparse = _is_poor_or_sparse_fit(mapping_result, job_signals)

    # Summary — grounded against corpus when the displayed "before" was empty or thin
    if (
        llm_summary_after
        and not poor_sparse
        and _grounded_rewrite_ok(working_summary, llm_summary_after, corpus=corpus)[0]
        and _summary_acceptable_for_output(llm_summary_after)
    ):
        summary_after = _trim_redundant_words(_strip_bad_summary_phrases(llm_summary_after))
        summary_why = (llm_summary_why or "").strip() or (
            "Adjusted summary into short professional prose grounded in your resume."
        )
    else:
        if llm_summary_after and poor_sparse:
            guardrail_notes.append(
                "Sparse overlap with the posting; skipped open-ended summary rewrite in favor of resume-grounded wording."
            )
        if llm_summary_after and not _grounded_rewrite_ok(
            working_summary, llm_summary_after, corpus=corpus
        )[0]:
            _, reason = _grounded_rewrite_ok(
                working_summary, llm_summary_after, corpus=corpus
            )
            guardrail_notes.append(f"Summary rewrite rejected ({reason}); used deterministic edit.")
        elif llm_summary_after and not _summary_acceptable_for_output(llm_summary_after):
            guardrail_notes.append(
                "Summary rewrite rejected (readability, meta phrasing, or validation); used deterministic prose."
            )
        summary_after, summary_why = _deterministic_summary(
            working_summary,
            corpus_lower,
            keywords,
            has_strong_requirement_match=has_strong,
        )

    if not _grounded_rewrite_ok(working_summary, summary_after, corpus=corpus)[0]:
        summary_after = _trim_redundant_words(_strip_bad_summary_phrases(working_summary))
        summary_why = "Kept summary wording conservative after validation checks."
        guardrail_notes.append(
            "Summary output failed validation against your resume text; reverted to the working draft."
        )
    elif not _summary_acceptable_for_output(summary_after):
        summary_after, summary_why = _deterministic_summary(
            working_summary,
            corpus_lower,
            keywords,
            has_strong_requirement_match=has_strong,
        )
        guardrail_notes.append("Summary failed validation; applied deterministic sentences.")

    summary_after, summary_why = _ensure_summary_always(
        summary_after,
        summary_why,
        working_summary,
        corpus,
        corpus_lower,
        mapping_result,
        job_signals,
        keywords,
        has_strong,
        resume_data=resume_data,
    )

    if not _summary_acceptable_for_output(summary_after):
        summary_after = _trim_redundant_words(
            _strip_bad_summary_phrases(
                _template_summary_from_signals(
                    mapping_result,
                    job_signals,
                    corpus,
                    corpus_lower,
                    keywords,
                    resume_data=resume_data,
                )
            )
        )
        if not _summary_acceptable_for_output(summary_after):
            summary_after = _default_resume_summary_fallback(resume_data, corpus)
        summary_why = (
            "Summary locked to a safe, short template after validation checks — no contact info or keyword mashups."
        )

    if _summary_input_has_jd_pollution(summary_after):
        summary_after = _trim_redundant_words(
            _strip_bad_summary_phrases(_resume_grounded_poor_fit_summary(corpus, corpus_lower, resume_data))
        )
        summary_why = (
            "Summary rebuilt from resume-only signals; removed posting or generic JD phrasing."
        )
        guardrail_notes.append("Final summary gate removed text not supported by the resume corpus.")

    summary_after = _enforce_summary_resume_only(summary_after, corpus, resume_data)

    bullet_changes: List[Dict[str, Any]] = []
    unchanged_targets: List[Dict[str, Any]] = []
    tailored_bullet_texts: List[str] = []
    expected_ids = [str(t.get("evidence_id") or "").strip() for t in targets if t.get("evidence_id")]

    staged: List[Dict[str, Any]] = []

    for t in targets:
        eid = str(t.get("evidence_id") or "").strip()
        company = t.get("company")
        section = str(t.get("section") or "experience")
        before = str(t.get("text") or "").strip()
        if not eid or not before:
            unchanged_targets.append(
                {
                    "evidence_id": eid or "(unknown)",
                    "reason": "missing evidence_id or text",
                }
            )
            continue

        why_mapper = str(t.get("reason") or "")
        must_t, strong_t, weak_t = _mapping_touch_counts(eid, mapping_result, job_signals)

        if not _bullet_text_in_resume(resume_data, before):
            guardrail_notes.append(
                f"Bullet {eid}: target text not found on resume (stale mapper target); left unchanged."
            )
            staged.append(
                {
                    "evidence_id": eid,
                    "company": company,
                    "section": section,
                    "before": before,
                    "after": before,
                    "why": "No rewrite applied; target text did not match current resume content.",
                    "mapper_reason": why_mapper,
                    "changed_line": False,
                    "stale": True,
                }
            )
            tailored_bullet_texts.append(before)
            unchanged_targets.append(
                {"evidence_id": eid, "reason": "target bullet text not found in resume corpus"}
            )
            continue

        candidate_after: str
        candidate_why: str

        if eid in llm_bullets:
            cand, w = llm_bullets[eid]
            candidate_after, candidate_why = cand, w
        else:
            candidate_after, candidate_why = _deterministic_bullet(before, keywords)

        ok, reject_reason = _bullet_rewrite_acceptable(before, candidate_after)
        if ok:
            final_after = _trim_redundant_words(candidate_after)
            final_why = candidate_why
        else:
            fb, fb_why = _deterministic_bullet(before, keywords)
            ok_fb, rej_fb = _bullet_rewrite_acceptable(before, fb)
            if ok_fb:
                final_after = _trim_redundant_words(fb)
                final_why = fb_why
            else:
                final_after = before
                final_why = (
                    "Kept original wording; proposed edits did not improve clarity or readability."
                )
            guardrail_notes.append(
                f"Bullet {eid}: rewrite rejected ({reject_reason}); "
                f"{'used deterministic edit' if ok_fb else 'kept original text'}"
                + (f" ({rej_fb})" if ok_fb is False and rej_fb else "")
            )

        material = _meaningful_bullet_rewrite(before, final_after)
        if not material:
            final_why = _honest_unchanged_reason(must_t, strong_t, weak_t)
        staged.append(
            {
                "evidence_id": eid,
                "company": company,
                "section": section,
                "before": before,
                "after": final_after,
                "why": final_why,
                "mapper_reason": why_mapper,
                "changed_line": material,
                "stale": False,
            }
        )
        tailored_bullet_texts.append(final_after)

    # At most 3 bullets receive grounded suggestion lines; prioritize weaker mapped lines.
    low_demo = _low_demonstrated_fit(mapping_result, job_signals)
    suggestion_candidates: List[Tuple[Tuple[int, ...], str]] = []
    for row in staged:
        if row.get("stale"):
            continue
        if row.get("changed_line"):
            continue
        eid = str(row.get("evidence_id") or "")
        must_t, strong_t, weak_t = _mapping_touch_counts(eid, mapping_result, job_signals)
        if low_demo:
            underspecified = weak_t > 0 or (must_t > 0 and strong_t < 2)
            pri = (0 if underspecified else 1, strong_t, -must_t, -weak_t, len(eid))
        else:
            pri = (strong_t, -must_t, -weak_t, len(eid))
        suggestion_candidates.append((pri, eid))
    suggestion_candidates.sort()
    suggestion_quota_eids = {eid for _, eid in suggestion_candidates[:3]}

    for row in staged:
        eid = str(row.get("evidence_id") or "").strip()
        if row.get("stale"):
            bullet_changes.append(
                {
                    "evidence_id": eid,
                    "company": row.get("company"),
                    "section": row.get("section"),
                    "before": row["before"],
                    "after": row["after"],
                    "why": row["why"],
                    "mapper_reason": row.get("mapper_reason") or "",
                    "mode": "suggestion",
                    "suggestions": [
                        "Save or re-export your resume so the file matches the text you see in your editor.",
                        "Re-run tailoring once the on-file bullets match what you intend to improve.",
                    ],
                }
            )
            continue

        before = str(row.get("before") or "")
        final_after = str(row.get("after") or "")
        material = bool(row.get("changed_line"))
        why_mapper = str(row.get("mapper_reason") or "")
        out_why = str(row.get("why") or "")
        must_t, strong_t, weak_t = _mapping_touch_counts(eid, mapping_result, job_signals)

        if material:
            mode = "rewrite"
            sugg = []
        elif eid in suggestion_quota_eids:
            sugg = _bullet_suggestions_with_fallback(
                eid, before, mapping_result, job_signals, corpus_lower
            )
            mode = "suggestion"
        else:
            sugg = []
            clearly_strong = strong_t >= 2 and weak_t == 0
            if clearly_strong:
                mode = "unchanged"
            else:
                # At most three bullets use mode "suggestion" (with suggestion lines); others stay unchanged with optional coaching in why.
                mode = "unchanged"
                tip = _coaching_tip_line_for_bullet(before, eid, mapping_result, job_signals)
                if tip and "Coaching:" not in out_why:
                    out_why = f"{out_why} Coaching: {tip}".strip()

        bullet_changes.append(
            {
                "evidence_id": eid,
                "company": row.get("company"),
                "section": row.get("section"),
                "before": before,
                "after": final_after,
                "why": out_why,
                "mapper_reason": why_mapper,
                "mode": mode,
                "suggestions": sugg,
            }
        )

    # Validate LLM id set vs targets
    if llm_bullets:
        got = set(llm_bullets.keys())
        exp = set(x for x in expected_ids if x)
        if exp and not exp <= got:
            guardrail_notes.append(
                "LLM omitted some evidence_ids; missing targets were filled deterministically or left unchanged."
            )
        extra = got - exp
        if extra:
            guardrail_notes.append(
                f"Ignored LLM entries for unknown evidence_ids: {sorted(extra)[:8]}."
            )

    guardrail_notes.append(
        "Rewrites were checked so new metrics, tools, or ownership claims are not introduced without support in the source bullet."
    )
    if _is_poor_or_sparse_fit(mapping_result, job_signals):
        guardrail_notes.append(
            "Posting overlap is limited; bullets and suggestions highlight honest improvements without inventing strong fit."
        )

    change_items: List[Dict[str, Any]] = [
        {
            "section": "summary",
            "before": summary_display_before or "(empty summary)",
            "after": summary_after,
            "why": summary_why,
            "company": None,
        }
    ]
    for bc in bullet_changes:
        change_items.append(
            {
                "section": bc.get("section") or "experience",
                "before": bc["before"],
                "after": bc["after"],
                "why": bc["why"],
                "company": bc.get("company"),
                "mode": bc.get("mode"),
                "suggestions": bc.get("suggestions") or [],
            }
        )

    return {
        "summary": {
            "before": summary_display_before or "",
            "after": summary_after,
            "why": summary_why,
        },
        "bullet_changes": bullet_changes,
        "unchanged_targets": unchanged_targets,
        "guardrail_notes": guardrail_notes,
        # Pipeline compatibility (output_builder, scoring)
        "tailored_summary": summary_after,
        "tailored_experience_bullets": tailored_bullet_texts,
        "tailored_skills": [],
        "change_items": change_items,
    }

"""Job description parsing and signal extraction."""

from __future__ import annotations

import re
from typing import List, Optional, Set, Tuple

from app.utils.text_cleaning import normalize_whitespace, trim_safe

# Frequent JD noise tokens — not useful as extracted “keywords”
_KEYWORD_SKIP_TOKENS = frozenset(
    """
    benefits compensation perks equity salary pto vacation insurance onboarding
    culture values mission diversity inclusion remote hybrid onsite
    fulltime parttime full-time part-time contract employment location
    wellness recruiting
    """.split()
)

_STOP = frozenset(
    """
    the a an and or for with from that this your our are was were been be being is it in to of as at by on if we you their will can may not no
    all any some such than then them they these those into about over after before under other also just more most very when what which while
    who how why work team role job using use used must have has had having do does did doing
    """.split()
)


def clean_job_text(job_description: str, context: str = "") -> dict:
    """
    Normalize JD (+ optional context) for downstream extraction.

    Filtered fields keep only requirement-grade chunks (same gate as extract_job_signals).
    Optional context is not trusted as requirements until it passes that gate.
    """
    jd = normalize_whitespace(job_description)
    ctx = normalize_whitespace(context) if context else ""
    jd_f = _text_to_requirement_filtered_blob(jd)
    ctx_f = _text_to_requirement_filtered_blob(ctx) if ctx else ""
    combined = trim_safe(jd + ("\n\n" + ctx if ctx else ""), max_chars=50_000)
    combined_f = trim_safe(jd_f + ("\n\n" + ctx_f if ctx_f else ""), max_chars=50_000)
    return {
        "job_description_clean": jd,
        "context_clean": ctx,
        "job_description_filtered": jd_f,
        "context_filtered": ctx_f,
        "combined_text": combined,
        "combined_filtered": combined_f,
    }


def _tokens(text: str) -> List[str]:
    return re.findall(r"[A-Za-z][A-Za-z0-9+#.\-]{1,}", text.lower())


def _sentence_and_line_candidates(text: str) -> List[str]:
    """Split into lines and rough sentences for requirement mining."""
    text = text.replace("\r", "\n")
    chunks: List[str] = []
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        chunks.append(line)
        for sent in re.split(r"(?<=[.!?])\s+", line):
            s = sent.strip()
            if 15 <= len(s) <= 280:
                chunks.append(s)
    return chunks


_BOILERPLATE_HINT = re.compile(
    r"\b(our values|we believe|passion|mission statement|culture|philosophy|why join us|about us|"
    r"equal opportunity|eoe|life at|who we are|brand promise|innovation culture)\b",
    re.I,
)

_HEADING_LINE = re.compile(
    r"^(about\s+|employment\s+type|job\s+type|job\s+description|job\s+category|what\s+we\s+re\s+looking\s+for|"
    r"overview|company\s+overview|who\s+we\s+are|why\s+join|benefits|perks|compensation|salary|pay\s+range|"
    r"total\s+rewards|what\s+we\s+offer|job\s+details|role\s+overview)\s*",
    re.I,
)

_BENEFITS_OR_COMP = re.compile(
    r"\b(401\s*\(?k\)?|health\s+(?:and\s+)?(?:dental|vision)?\s*insurance|dental\s+plan|vision\s+plan|"
    r"pto|paid\s+time\s+off|unlimited\s+pto|vacation\s+days|sick\s+leave|parental\s+leave|"
    r"tuition\s+reimbursement|commuter|wellness\s+(?:stipend|benefit)|"
    r"compensation\s+package|salary\s+range|base\s+salary|pay\s+range|equity|stock\s+options|\brsu\b|"
    r"bonus\s+structure|annual\s+bonus|perks?\s+include|benefits?\s+package|total\s+rewards|"
    r"what\s+we\s+offer|generous\s+benefits|competitive\s+(?:salary|compensation))\b",
    re.I,
)

_COMPANY_ABOUT = re.compile(
    r"\b(founded\s+in\s+\d{4}|we\s+are\s+a\s+(?:leading|global|fast[-\s]?growing|growing|premier)\s+|"
    r"our\s+company\s+(?:was|is|has)|we\s+started|started\s+in\s+(?:logistics|business|retail|tech|healthcare)\b|"
    r"about\s+(?:us|the\s+team|our\s+story|the\s+company)\b|"
    r"life\s+at\s+[A-Za-z]|join\s+our\s+(?:team|family|mission))\b",
    re.I,
)

_EMPLOYMENT_TYPE_ONLY = re.compile(
    r"^(?:full[\s-]?time|part[\s-]?time|contract(?:or)?|temporary|internship|w[-\s]?2|1099)\b[^.!?\n]{0,72}\.?$",
    re.I,
)
_REMOTE_SCHEDULE_ONLY = re.compile(
    r"^(?:remote|hybrid|on[-\s]?site|work\s+from\s+home|flexible\s+hours)\b[^.!?\n]{0,80}\.?$",
    re.I,
)

_ACTION_VERB = re.compile(
    r"\b(lead|manage|own|build|develop|analyze|analyse|design|implement|deliver|support|coordinate|drive|"
    r"validate|test|report|create|define|gather|facilitate|collaborate|execute|perform|document)\b",
    re.I,
)
# Tools / stacks — concrete skill signals (keep in sync with has_specific_signal)
_TOOLISH = re.compile(
    r"\b(sql|python|java|ruby|golang|go\b|scala|kotlin|typescript|javascript|react|angular|vue|node\.?js|"
    r"aws|azure|gcp|kubernetes|k8s|docker|terraform|jenkins|ansible|"
    r"jira|confluence|agile|scrum|kanban|"
    r"salesforce|dynamics|sap|workday|servicenow|"
    r"tableau|power\s*bi|looker|qlik|snowflake|databricks|redshift|bigquery|synapse|"
    r"excel|spreadsheet|access|"
    r"etl|elt|dbt|airflow|kafka|spark|hadoop|pandas|numpy|pyspark|"
    r"api|rest|graphql|grpc|microservices?|"
    r"crm|erp|bi\b|dba|nosql|mongodb|postgres|postgresql|mysql|oracle|sqlite|"
    r"slack|microsoft\s+teams|sharepoint|git|github|gitlab)\b",
    re.I,
)

# Domain / workflow — verifiable practice areas (includes testing, data validation; not bare “operations”)
_DOMAIN_WORKFLOW_SIGNAL = re.compile(
    r"\b(uat|qa|qc|defect|regression|stakeholder|workflow|workflows|pipeline|pipelines|reporting|analytics|analysis|"
    r"testing|test\s+plan|dashboard|dashboards|medicaid|medicare|hipaa|clinical|cms|requirements|acceptance|validation|"
    r"data\s+validation|validat(?:e|ing|ion)\s+data|"
    r"etl|crm|salesforce|jira|compliance|audit|forecasting|budgeting|procurement|"
    r"financial\s+close|revenue\s+cycle|supply\s+chain|logistics|inventory|"
    r"customer\s+success|onboarding|kyc|aml|fraud)\b",
    re.I,
)

# Output artifacts / deliverables (Part 1 — verifiable work products)
_OUTPUT_ARTIFACT_SIGNAL = re.compile(
    r"\b(dashboard|dashboards|report|reports|model|models|analysis|datasets?|"
    r"test\s+cases?|test\s+plans?|wireframes?|mockups?|prototypes?|specifications?|documentation)\b",
    re.I,
)

_SYSTEM_OR_ARTIFACT_SIGNAL = re.compile(
    r"\b(platform|platforms|dataset|datasets|data\s+warehouse|warehouse|lakehouse|datalake|"
    r"codebase|infrastructure|microservice|microservices|application|applications|"
    r"integration|integrations|release\s+(?:train|process)|ci/cd|ci\s*cd|deployment|deployments|"
    r"production\s+environment|sandbox|tenant|schema|schemas|migration|migrations)\b",
    re.I,
)

_CONCRETE_OUTPUT_SIGNAL = re.compile(
    r"\b(kpi|kpis|sla|slas|metric|metrics|milestone|milestones|roadmap|deliverable|deliverables|"
    r"sprint|backlog|okr|okrs|roi|run\s*rate|throughput|uptime|latency|accuracy)\b|"
    r"\d+\s*%|\b\d+%|"
    r"(?:reduce|reduces|reducing|increase|increases|increasing|decrease|decreases|grow|grows)\s+\w+\s+(?:by\s+)?\d|"
    r"\$\s*\d+|\b\d+\s*(?:k|m|bn|million|billion)\b",
    re.I,
)

_QUALIFICATION_SUBSTANTIVE = re.compile(
    r"\b(\d+\+?\s*(?:years?|yrs?)\s+(?:of\s+)?(?:experience|exp\.?)|"
    r"bachelor|master|phd|mba|bs\b|ba\b|ms\b|"
    r"pmp|cpa|cissp|comptia|aws\s+certified|professional\s+certification|licensed)\b",
    re.I,
)

_VAGUE_RESPONSIBILITY_VERB = re.compile(
    r"\b(collaborate|collaboration|support(?:ing)?|improve|improving|assist|assisting|assistance|"
    r"contribute|contributing|help|helping|work\s+with|partner(?:ing)?\s+with)\b",
    re.I,
)

_REQUIREMENT_FRAMING = re.compile(
    r"\b(must|required|minimum|qualification|qualifications|proficien|experienced|experience\s+(?:with|in)|"
    r"ability\s+to|responsible\s+for|demonstrated|demonstrable|skilled\s+in|familiarity\s+with|"
    r"understanding\s+of|working\s+knowledge|hands-on|years?\s+of|bachelor|master|phd|certification|certified)\b",
    re.I,
)

_BROAD_STRONG_ACTION = re.compile(
    r"\b(lead|manage|own|build|develop|analyze|analyse|design|implement|deliver|validate|test|report|create|define|"
    r"gather|execute|perform|document|coordinate|drive|automate|migrate|integrate|deploy|monitor|optimize|"
    r"troubleshoot|architect|model|forecast|schedule|prioritize|mentor|train|review|audit|refactor|"
    r"prototype|configure|administer|maintain)\b",
    re.I,
)

_STRICT_BENEFITS_WORDS = re.compile(
    r"\b(benefits|compensation|salary|perks|equity|bonus)\b|\b401\s*k\b|\b401k\b|"
    r"\b(health|dental|vision|medical)\s+coverage\b|\bcoverage\s+for\s+(?:health|dental|vision)\b",
    re.I,
)
_STRICT_VISION_DENTAL = re.compile(
    r"\b(vision|dental)\b.*\b(insurance|plan|coverage|benefits)\b|"
    r"\b(insurance|plan|coverage)\b.*\b(vision|dental)\b",
    re.I,
)
_HEALTHCARE_BENEFIT = re.compile(
    r"\bhealthcare\b.*\b(benefits|coverage|plan|insurance|package)\b|"
    r"\b(benefits|coverage|plan|insurance)\b.*\bhealthcare\b",
    re.I,
)

_EMPLOYMENT_META_PHRASE = re.compile(
    r"\b(employment\s+type|job\s+location|work\s+location)\b|^\s*location\s*:\s*|"
    r"^\s*(remote|hybrid|on[-\s]?site|full[-\s]?time|part[-\s]?time|contract)\s*$",
    re.I,
)

_MANIFESTO_STRICT = re.compile(
    r"\b(we\s+hire\s+people\s+who|the\s+future\s+of|our\s+values|we\s+believe|our\s+mission|"
    r"why\s+join|life\s+at\s+|who\s+we\s+are|our\s+company\s+is|"
    r"passionate\s+about\s+our|employee\s+experience|employer\s+of\s+choice)\b",
    re.I,
)

_PERSUASIVE_JD = re.compile(
    r"\b(you\s+will\s+(?:be|love|join|thrive)|you\s+'?ll\s+thrive|we\s+invite\s+you|come\s+join\s+us|"
    r"join\s+our\s+(?:mission|family|journey)|together\s+we\s+can|the\s+future\s+of|"
    r"we\s+hire\s+people\s+who)\b",
    re.I,
)

_GENERIC_NON_REQ = re.compile(
    r"\b(great\s+team\s+player|team\s+player|fast[-\s]?paced\s+environment|"
    r"dynamic\s+environment|rock\s*star|ninja|synergy|world[-\s]?class)\b",
    re.I,
)


def _word_count_line(s: str) -> int:
    return len(re.findall(r"[a-zA-Z']+", s or ""))


def _is_likely_boilerplate(line: str) -> bool:
    if _BOILERPLATE_HINT.search(line):
        return True
    if len(line) > 220:
        return True
    return False


def _requirement_score(line: str) -> int:
    lower = line.lower()
    score = 0
    if re.search(
        r"\b(required|must|minimum|preferred|qualification|experience|proficien|skilled|ability|familiar|understanding|demonstrated|years)\b",
        lower,
    ):
        score += 3
    if re.match(r"^[\-\u2022\u2023*•]\s*", line):
        score += 2
    if re.search(r"\d+\+?\s*(years?|yrs?)", lower):
        score += 2
    if re.search(r"\b(bs|ba|ms|phd|degree|certification)\b", lower):
        score += 1
    return score


def is_heading_like_line(line: str) -> bool:
    t = (line or "").strip()
    if not t:
        return True
    if len(t) > 130:
        return False
    low = t.lower().strip()
    if low in (
        "job description",
        "job details",
        "role overview",
        "employment type",
        "about us",
        "about the company",
    ):
        return True
    if _HEADING_LINE.match(t):
        return True
    if re.match(r"^about\s+\S", t, re.I) and _word_count_line(t) <= 12:
        return True
    if _word_count_line(t) <= 5 and "experience" not in low and "years" not in low and "degree" not in low:
        # Short lines like "Demonstrated strength in analytics" are not section headings.
        if _TOOLISH.search(t) or _DOMAIN_WORKFLOW_SIGNAL.search(t):
            return False
        if not re.search(r"\b(must|required|preferred|sql|python|uat|qa)\b", low):
            return True
    return False


def is_philosophy_like_line(line: str) -> bool:
    t = (line or "").strip()
    if _is_likely_boilerplate(t):
        return True
    if re.search(
        r"\b(we believe|our mission|our values|join a team|passionate about|manifesto|"
        r"game-changer|rockstar|ninja|synergy|world-class)\b",
        t,
        re.I,
    ):
        return True
    if t.count('"') >= 2 and _word_count_line(t) >= 22:
        return True
    if t.count("—") >= 2 and _word_count_line(t) > 35:
        return True
    return False


_MARKETING_OR_MANIFESTO = re.compile(
    r"\b(we\s+are\s+building|we\s+value\s+people|you\s+will\s+be|you\s+'?ll\s+join|join\s+our\s+mission|"
    r"our\s+culture\s+is|life\s+at\s+|why\s+you\s+'?ll\s+love|come\s+be\s+part|"
    r"reimagining|reinventing\s+the|together\s+we\s+can)\b",
    re.I,
)


def is_marketing_or_manifesto_line(line: str) -> bool:
    """Persuasive / narrative JD copy, not a checkable requirement."""
    t = (line or "").strip()
    if not t:
        return True
    if is_philosophy_like_line(t) or is_heading_like_line(t):
        return True
    if _MARKETING_OR_MANIFESTO.search(t) and not _TOOLISH.search(t):
        if not _ACTION_VERB.search(t):
            return True
    if _word_count_line(t) > 55 and _requirement_score(t) < 2 and not _TOOLISH.search(t):
        return True
    if t.count("!") >= 2 and _word_count_line(t) > 22:
        return True
    if re.search(r"\b(you\s+are|you\s+'?re|we\s+invite|we\s+seek\s+someone\s+who)\b", t, re.I):
        if not re.search(
            r"\b(years|degree|sql|python|experience\s+with|must|required|certification)\b",
            t,
            re.I,
        ):
            return True
    return False


def is_benefits_or_compensation_line(line: str) -> bool:
    """Benefits, perks, pay, equity — not role requirements."""
    t = (line or "").strip()
    if not t:
        return True
    if _BENEFITS_OR_COMP.search(t):
        return True
    if re.search(r"\$\s*\d|\d+\s*k\s+base\s+salary", t, re.I):
        return True
    return False


def is_employment_type_or_schedule_line(line: str) -> bool:
    """Employment type / remote-only lines without skill or tool substance."""
    t = (line or "").strip()
    if not t:
        return True
    wc = _word_count_line(t)
    if wc > 22:
        return False
    if _EMPLOYMENT_TYPE_ONLY.match(t) or _REMOTE_SCHEDULE_ONLY.match(t):
        if not _TOOLISH.search(t) and not _ACTION_VERB.search(t):
            return True
    if wc <= 10 and re.match(
        r"^(?:full|part|contract|temporary|remote|hybrid|on[-\s]?site)\b", t, re.I
    ):
        if not _TOOLISH.search(t) and _requirement_score(t) < 2:
            return True
    return False


def is_company_about_line(line: str) -> bool:
    """Employer marketing / about copy, not a checkable requirement."""
    t = (line or "").strip()
    if not t:
        return True
    if _COMPANY_ABOUT.search(t) and not _TOOLISH.search(t):
        if not re.search(
            r"\b(years|degree|sql|python|experience\s+with|must|required|certification|uat|qa)\b",
            t,
            re.I,
        ):
            return True
    if re.match(r"^about\s+", t, re.I) and _word_count_line(t) >= 18 and _requirement_score(t) < 2:
        if not _TOOLISH.search(t):
            return True
    return False


def is_values_or_manifesto_line(line: str) -> bool:
    """Values, culture pitch, or persuasive manifesto — not a requirement line."""
    t = (line or "").strip()
    if is_philosophy_like_line(t) or is_marketing_or_manifesto_line(t):
        return True
    if re.search(
        r"\b(our\s+values|culture\s+of|people\s+first|inclusion\s+and\s+diversity|"
        r"belonging|employee\s+experience|employer\s+of\s+choice)\b",
        t,
        re.I,
    ):
        if not _TOOLISH.search(t) and _requirement_score(t) < 3:
            return True
    return False


def is_benefits_line(line: str) -> bool:
    """Benefits / compensation / coverage phrasing — reject as requirements (strict)."""
    t = (line or "").strip()
    if not t:
        return True
    if is_benefits_or_compensation_line(t):
        return True
    tl = t.lower()
    if _STRICT_BENEFITS_WORDS.search(tl):
        return True
    if _STRICT_VISION_DENTAL.search(tl):
        return True
    if _HEALTHCARE_BENEFIT.search(tl):
        return True
    return False


def is_heading_line(line: str) -> bool:
    """Section headings and labels — not requirements."""
    return is_heading_like_line(line)


def is_manifesto_or_values_line(line: str) -> bool:
    """Manifesto, values pitch, or persuasive employer copy — not a requirement."""
    t = (line or "").strip()
    if not t:
        return True
    if is_values_or_manifesto_line(t):
        return True
    if _MANIFESTO_STRICT.search(t) and not _TOOLISH.search(t):
        if _word_count_line(t) < 12 or not _ACTION_VERB.search(t):
            return True
    if _PERSUASIVE_JD.search(t) and not _TOOLISH.search(t):
        if not re.search(
            r"\b(years|degree|sql|python|must|required|certification|experience\s+with)\b",
            t,
            re.I,
        ):
            return True
    return False


def is_employment_meta_line(line: str) -> bool:
    """Employment type, location-only, schedule-only lines — not skill requirements."""
    t = (line or "").strip()
    if not t:
        return True
    if _EMPLOYMENT_META_PHRASE.search(t) and _word_count_line(t) < 24:
        if not _TOOLISH.search(t) and not _DOMAIN_WORKFLOW_SIGNAL.search(t):
            return True
    if re.search(r"\bemployment\s+type\b", t, re.I) and _word_count_line(t) < 28:
        if not _TOOLISH.search(t):
            return True
    return is_employment_type_or_schedule_line(t)


def has_specific_signal(text: str) -> bool:
    """
    Verifiable specificity for a requirement line: at least one of
    tool/stack, system/object, domain/workflow, output artifact, measurable output, or substantive qualification.
    """
    t = (text or "").strip()
    if not t:
        return False
    if _TOOLISH.search(t):
        return True
    if _SYSTEM_OR_ARTIFACT_SIGNAL.search(t):
        return True
    if _DOMAIN_WORKFLOW_SIGNAL.search(t):
        return True
    if _OUTPUT_ARTIFACT_SIGNAL.search(t):
        return True
    if _CONCRETE_OUTPUT_SIGNAL.search(t):
        return True
    if _QUALIFICATION_SUBSTANTIVE.search(t):
        return True
    return False


def has_action_verb(text: str) -> bool:
    """
    Action verb and/or requirement framing (must, years, proficiency, experience with, etc.).
    Pair with has_specific_signal — a valid requirement needs both.
    """
    t = (text or "").strip()
    if not t:
        return False
    if _REQUIREMENT_FRAMING.search(t):
        return True
    if _BROAD_STRONG_ACTION.search(t):
        return True
    if _ACTION_VERB.search(t):
        return True
    # Short multi-skill or skill-list lines (no explicit verb)
    tl = t.strip()
    if _TOOLISH.search(t) and (
        re.search(r"\b(?:and|or)\b", tl, re.I) or _word_count_line(t) <= 14
    ):
        return True
    if _requirement_score(t) >= 4:
        return True
    return False


def is_generic_responsibility_line(line: str) -> bool:
    """
    Vague collaborate/support/improve/etc. without tools, systems, domain, or concrete output.
    These inflate poor-fit scores and pollute summaries when treated as requirements.
    """
    t = (line or "").strip()
    if len(t) < 12:
        return False
    if not _VAGUE_RESPONSIBILITY_VERB.search(t):
        return False
    if has_specific_signal(t):
        return False
    return True


def is_non_actionable_line(line: str) -> bool:
    """
    Hard reject: junk that must never become a requirement (JD or context).
    Applied before requirement extraction.
    """
    t = (line or "").strip()
    if not t:
        return True
    if is_benefits_line(t):
        return True
    if is_company_about_line(t):
        return True
    if is_manifesto_or_values_line(t):
        return True
    if is_heading_line(t):
        return True
    if is_employment_meta_line(t):
        return True
    if is_philosophy_like_line(t):
        return True
    if is_marketing_or_manifesto_line(t):
        return True
    if _GENERIC_NON_REQ.search(t) and not _TOOLISH.search(t) and _word_count_line(t) < 20:
        return True
    if is_generic_responsibility_line(t):
        return True
    wc = _word_count_line(t)
    if wc > 25 and not (has_specific_signal(t) and has_action_verb(t)):
        return True
    return False


def _filter_candidate_chunks(candidates: List[str]) -> List[str]:
    out: List[str] = []
    seen: Set[str] = set()
    for c in candidates:
        c = re.sub(r"\s+", " ", c.strip())
        if len(c) < 15:
            continue
        if not is_actionable_requirement_line(c):
            continue
        key = c.lower()[:120]
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out


def _text_to_requirement_filtered_blob(text: str) -> str:
    """Join only requirement-grade chunks (for keyword / signal extraction)."""
    if not text.strip():
        return ""
    chunks = _sentence_and_line_candidates(text)
    kept = _filter_candidate_chunks(chunks)
    if not kept:
        return ""
    return normalize_whitespace("\n".join(kept))


def is_actionable_requirement_line(line: str) -> bool:
    """Valid requirement only if has_action_verb AND has_specific_signal (plus hygiene filters)."""
    t = (line or "").strip()
    if len(t) < 16:
        return False
    if len(t) > 240:
        return False
    if is_non_actionable_line(t):
        return False
    if not has_specific_signal(t):
        return False
    if not has_action_verb(t):
        return False
    return True


def is_requirement_grade_candidate(line: str) -> bool:
    """Single gate: line could plausibly be a skill, tool, responsibility, or qualification."""
    return is_actionable_requirement_line(line)


def passes_all_filters(line: str) -> bool:
    """
    Single source of truth for whether extracted text may become a validated requirement.
    Synonym for is_actionable_requirement_line (benefits, about, manifesto, generic, specificity, action).
    """
    return is_actionable_requirement_line(line)


def requirement_allowed_in_pipeline(requirement_text: str, job_signals: Optional[dict]) -> bool:
    """
    Whether a requirement row may affect scoring, fit heuristics, or recruiter-facing output.
    Must pass actionable rules and appear in validated_requirements (single source of truth).
    If there is no validated list, requirement-derived pipeline output is disabled — do not fall back to raw JD.
    """
    t = (requirement_text or "").strip()
    if not t:
        return False
    if not is_actionable_requirement_line(t):
        return False
    if job_signals is None or not isinstance(job_signals, dict):
        return False
    vr = job_signals.get("validated_requirements")
    if not isinstance(vr, list) or len(vr) == 0:
        return False
    fp = re.sub(r"\s+", " ", t.lower())[:48]
    for x in vr:
        if not x:
            continue
        if re.sub(r"\s+", " ", str(x).lower())[:48] == fp:
            return True
    return False


def _pick_core_requirements(candidates: List[str]) -> List[str]:
    scored: List[Tuple[int, str]] = []
    seen: Set[str] = set()
    for c in candidates:
        c = c.strip()
        if len(c) < 15 or len(c) > 240:
            continue
        if not is_actionable_requirement_line(c):
            continue
        if _is_likely_boilerplate(c):
            continue
        key = re.sub(r"\s+", " ", c.lower())
        if key in seen:
            continue
        seen.add(key)
        scored.append((_requirement_score(c), c))
    scored.sort(key=lambda x: (-x[0], len(x[1])))
    out: List[str] = []
    for _, line in scored:
        line = re.sub(r"\s+", " ", line).strip()
        if line not in out:
            out.append(line)
        if len(out) >= 10:
            break
    # Ensure at least a few items if JD is unstructured: fall back to longer clauses
    if len(out) < 5:
        for c in candidates:
            c = re.sub(r"\s+", " ", c.strip())
            if 25 <= len(c) <= 200 and c not in out:
                if not is_actionable_requirement_line(c):
                    continue
                out.append(c)
            if len(out) >= 5:
                break
    return out[:10]


def _split_preferred_section(text: str) -> Tuple[str, str]:
    """Rough split: body vs 'preferred/nice/bonus' style tail."""
    lower = text.lower()
    markers = ("preferred qualifications", "nice to have", "bonus", "plus:", "preferred:")
    idx = len(text)
    for m in markers:
        p = lower.find(m)
        if p != -1:
            idx = min(idx, p)
    if idx < len(text) - 20:
        return text[:idx].strip(), text[idx:].strip()
    return text, ""


def _keywords_ranked(blob: str, limit: int = 15) -> List[str]:
    counts: dict[str, int] = {}
    for w in _tokens(blob):
        if len(w) < 3 or w in _STOP:
            continue
        counts[w] = counts.get(w, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], -len(kv[0]), kv[0]))
    out: List[str] = []
    seen: Set[str] = set()
    for w, _ in ranked:
        wl = w.lower()
        if wl in _KEYWORD_SKIP_TOKENS:
            continue
        if wl in seen:
            continue
        seen.add(wl)
        out.append(w)
        if len(out) >= limit:
            break
    return out


def _role_focus_labels(blob: str) -> List[str]:
    lower = blob[:4000].lower()
    labels: List[str] = []
    patterns = [
        (r"\b(data scientist|machine learning|ml engineer|ai\b)", "Data / ML"),
        (r"\b(software|backend|frontend|full[\s-]?stack|developer|engineer)\b", "Software engineering"),
        (r"\b(product manager|product owner)\b", "Product"),
        (r"\b(project manager|program manager)\b", "Program / project delivery"),
        (r"\b(designer|ux|ui)\b", "Design / UX"),
        (r"\b(sales|account executive|business development)\b", "Sales / business development"),
        (r"\b(marketing|growth|content)\b", "Marketing / growth"),
        (r"\b(finance|accounting|fp&a)\b", "Finance"),
        (r"\b(hr|people|talent|recruiter)\b", "People / HR"),
        (r"\b(consultant|consulting)\b", "Consulting"),
        (r"\b(analyst|analytics|bi\b|business intelligence)\b", "Analytics"),
        (r"\b(lead|manager|director|head of|vp)\b", "Leadership / senior IC"),
    ]
    seen: Set[str] = set()
    for pat, label in patterns:
        if re.search(pat, lower) and label not in seen:
            seen.add(label)
            labels.append(label)
    if not labels:
        labels.append("Role focus: general / mixed")
    return labels[:6]


def extract_job_signals(cleaned_text: str, context: str = "") -> dict:
    """
    Deterministic extraction: core requirements, keywords, role focus.
    JD and optional context must be pre-filtered or raw; candidates are always
    requirement-grade filtered here so benefits/about copy does not become requirements.
    Output keys are stable for the API contract.
    """
    jd = normalize_whitespace(cleaned_text)
    ctx = normalize_whitespace(context) if context else ""
    blob = normalize_whitespace(jd + ("\n" + ctx if ctx else ""))
    main, preferred_blob = _split_preferred_section(blob)

    candidates_main = _filter_candidate_chunks(_sentence_and_line_candidates(main))
    candidates_pref = (
        _filter_candidate_chunks(_sentence_and_line_candidates(preferred_blob)) if preferred_blob else []
    )

    core = _pick_core_requirements(candidates_main + candidates_pref)
    if len(core) < 5:
        core = _pick_core_requirements(_filter_candidate_chunks(_sentence_and_line_candidates(blob)))

    preferred_reqs: List[str] = []
    for c in candidates_pref:
        c = re.sub(r"\s+", " ", c.strip())
        if (
            15 <= len(c) <= 220
            and c not in core
            and not _is_likely_boilerplate(c)
            and is_actionable_requirement_line(c)
        ):
            preferred_reqs.append(c)
        if len(preferred_reqs) >= 5:
            break

    # Single source of truth: ordered, deduped, priority-tagged; downstream must use this only.
    validated_requirements: List[str] = []
    validated_requirement_priorities: List[str] = []
    seen_val: Set[str] = set()

    def _push_validated(raw: str, priority: str) -> None:
        line = re.sub(r"\s+", " ", raw.strip())
        if not passes_all_filters(line):
            return
        key = re.sub(r"\s+", " ", line.lower())[:120]
        if key in seen_val:
            return
        seen_val.add(key)
        validated_requirements.append(line)
        validated_requirement_priorities.append(priority)

    for line in core:
        _push_validated(line, "must_have")
    for line in preferred_reqs:
        _push_validated(line, "preferred")

    must_have_requirements = [
        validated_requirements[i]
        for i in range(len(validated_requirements))
        if validated_requirement_priorities[i] == "must_have"
    ][:10]
    preferred_requirements = [
        validated_requirements[i]
        for i in range(len(validated_requirements))
        if validated_requirement_priorities[i] == "preferred"
    ][:10]

    # Keywords only from validated requirement text — never raw JD/blob (prevents manifesto/about tokens).
    kw_join = normalize_whitespace(" ".join(validated_requirements))
    keywords = _keywords_ranked(kw_join, limit=15) if kw_join.strip() else []

    rf_blob = _text_to_requirement_filtered_blob(blob)
    role_focus = _role_focus_labels(
        rf_blob if rf_blob.strip() else (kw_join if kw_join.strip() else jd[:4000])
    )

    # Downstream must treat validated_requirements (+ priorities) as the only requirement lines;
    # must_have_requirements / preferred_requirements are views of that same list.
    return {
        "validated_requirements": validated_requirements,
        "validated_requirement_priorities": validated_requirement_priorities,
        "must_have_requirements": must_have_requirements,
        "preferred_requirements": preferred_requirements,
        "keywords": keywords[:15],
        "role_focus": role_focus,
    }

"""Rule-based scoring engine.

Generic - all applicant-specific tuning (keyword groups, markets, thresholds,
penalties, CV-selection rules) lives in profile/scoring.yaml, loaded via
radar/config.py. After editing that file run `python -m radar.cli rescore`.
"""
import re

from .config import market, scoring

_CFG = scoring()

CANDIDATE_YEARS = _CFG["candidate_years"]
LLM_FLOOR = _CFG["thresholds"]["llm_floor"]


def _thresholds(country):
    """(apply, consider) cutoffs - a market may override the global ones."""
    g = _CFG["thresholds"]
    m = market(country).get("thresholds") or {}
    return m.get("apply", g["apply"]), m.get("consider", g["consider"])

_KEYWORD_GROUPS = [(g["label"], [k.lower() for k in g["keywords"]], g["points"], g.get("match", "full"))
                   for g in _CFG["keyword_groups"]]
_VISA_CUES = [c.lower() for c in _CFG.get("visa_cues", [])]
_PENALTY = _CFG["overreach_penalty"]
_SENIOR_TITLE_RE = re.compile(_CFG["senior_title_pattern"], re.I)
_NATIVE_LANG_CUES = [c.lower() for c in _CFG["native_language_cues"]]

_DEFAULT_SPONSOR_GAP = "Visa sponsorship not mentioned - verify before applying"


def score(j):
    """Keyword-rule score for a job. Returns (score, matched_strength_labels)."""
    full = f"{j.title} {j.company} {j.description}".lower()
    title = (j.title or "").lower()
    total = 0
    strengths = []
    for label, keys, pts, match in _KEYWORD_GROUPS:
        haystack = title if match == "title" else full
        if any(k in haystack for k in keys):
            total += pts
            strengths.append(label)

    m = market(j.country)
    if m.get("score_bonus"):
        total += m["score_bonus"]
        if m.get("score_bonus_label"):
            strengths.append(m["score_bonus_label"])

    return min(total, 100), strengths


def classify(j):
    """Fill in visa / language fields and note concrete gaps."""
    t = f"{j.title} {j.description}".lower()
    m = market(j.country)
    gaps = []

    mode = m.get("visa", "verify")
    if mode == "not_needed":
        j.visa_status = "NOT_NEEDED_FOR_USER"
    elif mode == "confirm_if_mentioned":
        if _VISA_CUES and any(k in t for k in _VISA_CUES):
            j.visa_status = "CONFIRMED"
        else:
            j.visa_status = "UNKNOWN"
            gaps.append(m.get("visa_gap", _DEFAULT_SPONSOR_GAP))
    else:  # verify
        j.visa_status = "UNKNOWN"
        j.work_authorization = "UNKNOWN"
        gaps.append(m.get("visa_gap", "Work authorization not confirmed - verify before applying"))

    j.language_requirement = _language_requirement(m, t, gaps)
    j.gaps = gaps
    return j


_LEVELS = ("business_or_higher", "preferred_or_conversational", "english_friendly")
_LEVEL_LABEL = {
    "business_or_higher": "BUSINESS_OR_HIGHER",
    "preferred_or_conversational": "PREFERRED_OR_CONVERSATIONAL",
    "english_friendly": "ENGLISH_FRIENDLY",
}


def _language_requirement(m, text, gaps):
    lang = m.get("language")
    if not lang:  # market with no local-language barrier for the applicant
        return "NOT_A_BARRIER_FOR_USER"
    for level in _LEVELS:
        cues = [c.lower() for c in lang.get(level, [])]
        if cues and any(k in text for k in cues):
            if level == "business_or_higher" and lang.get("gap"):
                gaps.append(lang["gap"])
            return _LEVEL_LABEL[level]
    return "UNKNOWN"


_CV = _CFG["cv_selection"]


def cv(j):
    if market(j.country).get("match_cv") is False:
        return ""  # e.g. Vienna stopgap jobs - a one-page service CV, not a tech variant
    t = f"{j.title} {j.description}".lower()
    for rule in _CV.get("rules", []):
        if any(k.lower() in t for k in rule["keywords"]):
            return rule["cv"]
    by_market = _CV.get("by_market", {})
    if j.country in by_market:
        return by_market[j.country]
    return _CV["default"]


# --- Seniority / experience / native-language screens ------------------------
# Pure text helpers - also used by the dashboard to hide out-of-reach roles.

# "5+ years of experience", "5 Jahre Berufserfahrung", "5年以上の経験" - only
# count a figure when an experience word sits within ~30 chars either side, so
# company blurbs ("25 years of market presence") don't trip it.
_CTX = r"experience|exp\b|erfahrung|berufserfahrung|経験|working"
_YRS = r"(\d{1,2})\s*\+?\s*(?:years?|yrs?|jahre|年)"
_YEARS_RE = re.compile(
    rf"(?:{_YRS}[^.\n]{{0,30}}?(?:{_CTX})|(?:{_CTX})[^.\n]{{0,30}}?{_YRS})", re.I
)


def required_years(text):
    """Largest 'N years of experience' figure mentioned in the text, else 0."""
    nums = [int(a or b) for a, b in _YEARS_RE.findall(text or "")]
    return max(nums, default=0)


def is_senior_title(title):
    return bool(_SENIOR_TITLE_RE.search(title or ""))


def requires_native_language(country, language_requirement, text):
    """True if the role needs a business/native language the applicant lacks.
    Set `native_language_ok: true` on a market where the applicant is a native
    speaker to opt out."""
    if market(country).get("native_language_ok"):
        return False
    if language_requirement == "BUSINESS_OR_HIGHER":
        return True
    return any(cue in (text or "").lower() for cue in _NATIVE_LANG_CUES)


def _overreach_penalty(j):
    """Points to subtract, and gap notes, for roles beyond a candidate with
    CANDIDATE_YEARS of experience. Call after classify()."""
    text = f"{j.title} {j.description}"
    penalty, notes = 0, []

    years = required_years(text)
    if years > CANDIDATE_YEARS:
        penalty += min(
            _PENALTY["years_base"] + _PENALTY["years_step"] * (years - CANDIDATE_YEARS),
            _PENALTY["years_cap"],
        )
        notes.append(f"Asks for ~{years}y experience; candidate has ~{CANDIDATE_YEARS}y")
    if is_senior_title(j.title):
        penalty += _PENALTY["senior_title"]
        notes.append("Senior/lead title - likely above candidate's level")
    if requires_native_language(j.country, j.language_requirement, text):
        penalty += _PENALTY["native_language"]
        notes.append("Needs native / business-level local language")

    return penalty, notes


def evaluate(j):
    """Run the full rule-based pipeline on a Job in place: score, classify, recommend."""
    j.rule_score, j.strengths = score(j)
    classify(j)
    penalty, penalty_notes = _overreach_penalty(j)
    if penalty:
        j.rule_score = max(0, j.rule_score - penalty)
        j.gaps = penalty_notes + j.gaps
    j.recommended_cv = cv(j)
    j.reason = "; ".join(j.strengths[:3] + j.gaps[:2]) or "No strong signals matched"
    apply_cut, consider_cut = _thresholds(j.country)
    j.recommendation = (
        "APPLY" if j.rule_score >= apply_cut
        else "CONSIDER" if j.rule_score >= consider_cut
        else "SKIP"
    )
    return j

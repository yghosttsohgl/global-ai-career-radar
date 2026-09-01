import math
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

import streamlit as st

from radar.config import scoring as scoring_config
from radar.db import init, jobs
from radar.scoring import is_senior_title, required_years, requires_native_language

PER_PAGE = 10
VERDICT_COLOR = {"APPLY": "green", "CONSIDER": "orange", "SKIP": "red", "UNSCORED": "gray"}

_MARKETS = scoring_config()["markets"]
MARKET_NAMES = list(_MARKETS)
CANDIDATE_YEARS = scoring_config()["candidate_years"]
LANG_LABEL = {
    name: (m.get("language") or {}).get("label", "Language")
    for name, m in _MARKETS.items()
}

# Display-only overrides for the market navigation. The internal name (also the
# DB `country` value and the key in scoring.yaml) is unchanged - only the label,
# icon, colour and one-line blurb differ.
MARKET_LABELS = {name: name for name in MARKET_NAMES}
MARKET_ICONS = {name: ":material/work:" for name in MARKET_NAMES}
MARKET_BLURB = {}

MARKET_LABELS.update({"Remote": "Remote (global)", "Vienna": "Part-time (local)"})
MARKET_ICONS.update({
    "Japan": ":material/travel_explore:",
    "Austria": ":material/apartment:",
    "Remote": ":material/home_work:",
    "Vienna": ":material/storefront:",
})
MARKET_BLURB["Vienna"] = (
    "Local Vienna hospitality / retail / service roles - flexible, low-requirement "
    "stopgap work for interim income and German practice while job-hunting."
)

# One accent colour per market. `rgb` drives the scoped button CSS; `badge` is the
# nearest st.badge colour name for the heading. Unknown markets fall back to slate.
MARKET_RGB = {
    "Japan": "147,51,234",    # purple
    "Austria": "37,99,235",   # blue
    "Remote": "13,148,136",   # teal
    "Vienna": "217,119,6",    # amber
}
DEFAULT_RGB = "100,116,139"   # slate
MARKET_BADGE = {"Japan": "violet", "Austria": "blue", "Remote": "green", "Vienna": "orange"}

FILTER_DEFAULTS = {"min": 40, "yrs": CANDIDATE_YEARS, "snr": True, "nat": True}

# Pins each card's score to the top-right corner of its bordered box.
CARD_CSS = """
<style>
[class*="st-key-jobcard_"] { position: relative; }
[class*="st-key-jobcard_"] h3 { padding-right: 3.5rem; }
[class*="st-key-jobscore_"] {
    position: absolute;
    top: 0.5rem;
    right: 0.85rem;
    z-index: 2;
    width: auto;
}
[class*="st-key-jobscore_"] p { margin: 0; font-size: 1.05rem; font-weight: 700; }
</style>
"""

init()
st.set_page_config(page_title="Career Radar", page_icon=":material/radar:", layout="wide")


@st.cache_data(ttl=300)
def all_jobs():
    return jobs()


def combined_score(j):
    return j["llm_score"] if j["llm_score"] is not None else j["rule_score"]


def combined_verdict(j):
    return j["llm_verdict"] or j["recommendation"] or "UNSCORED"


def job_text(j):
    return f"{j['title']} {j['description'] or ''}"


def auth_display(visa_status):
    """Human-readable label + badge colour for a job's visa_status enum."""
    return {
        "NOT_NEEDED_FOR_USER": ("Work permit OK", "green"),
        "CONFIRMED": ("Visa sponsored", "green"),
        "UNKNOWN": ("Visa status unclear", "gray"),
    }.get(visa_status, (str(visa_status).replace("_", " ").capitalize(), "gray"))


def lang_display(country, requirement):
    """Human-readable label + badge colour for a job's language_requirement enum."""
    lang = LANG_LABEL.get(country, "Local language")
    return {
        "NOT_A_BARRIER_FOR_USER": ("No language barrier", "green"),
        "ENGLISH_FRIENDLY": ("English-friendly", "green"),
        "PREFERRED_OR_CONVERSATIONAL": (f"{lang} a plus", "gray"),
        "BUSINESS_OR_HIGHER": (f"Business {lang} required", "gray"),
        "UNKNOWN": (f"{lang} requirement unclear", "gray"),
    }.get(requirement, (str(requirement).replace("_", " ").capitalize(), "gray"))


def filter_values(country):
    """The market's current filter settings (its widget state, or the defaults)."""
    return (
        st.session_state.get(f"min_{country}", FILTER_DEFAULTS["min"]),
        st.session_state.get(f"yrs_{country}", FILTER_DEFAULTS["yrs"]),
        st.session_state.get(f"snr_{country}", FILTER_DEFAULTS["snr"]),
        st.session_state.get(f"nat_{country}", FILTER_DEFAULTS["nat"]),
    )


def passes(j, minimum, max_years, hide_senior, hide_native):
    if combined_score(j) < minimum:
        return None  # below score cutoff - not counted as "hidden by filters"
    text = job_text(j)
    if max_years < 15 and required_years(text) > max_years:
        return False
    if hide_senior and is_senior_title(j["title"]):
        return False
    if hide_native and requires_native_language(j["country"], j["language_requirement"], text):
        return False
    return True


def market_jobs(country):
    return [j for j in all_jobs() if j["country"] == country]


def filtered_count(country):
    vals = filter_values(country)
    return sum(1 for j in market_jobs(country) if passes(j, *vals) is True)


def render_card(j):
    score = combined_score(j)
    verdict = combined_verdict(j)
    llm_scored = j["llm_score"] is not None
    years = required_years(job_text(j))
    senior = is_senior_title(j["title"])
    native = requires_native_language(j["country"], j["language_requirement"], job_text(j))

    score_color = VERDICT_COLOR.get(verdict, "gray")

    with st.container(border=True, key=f"jobcard_{j['fingerprint']}"):
        st.container(key=f"jobscore_{j['fingerprint']}").markdown(
            f":{score_color}[**{round(score)}%**]"
        )
        st.markdown(f"### {j['title']}")

        badges = st.container(horizontal=True)
        badges.badge(verdict, color=score_color)
        if llm_scored:
            badges.badge("AI-scored", icon=":material/smart_toy:", color="violet")
        else:
            badges.badge("Rule-scored", icon=":material/rule:", color="gray")
        if senior:
            badges.badge("Senior title", icon=":material/trending_up:", color="gray")
        if years:
            badges.badge(f"{years}+ yrs wanted", icon=":material/schedule:", color="gray")
        if native:
            badges.badge("Native language", icon=":material/translate:", color="gray")

        st.markdown(
            f":material/apartment: **{j['company']}** &nbsp;&nbsp;·&nbsp;&nbsp; "
            f":material/place: **{j['location'] or 'Location unknown'}** &nbsp;&nbsp;·&nbsp;&nbsp; "
            f":gray[{j['country']}]"
        )

        meta = st.container(horizontal=True)
        auth_label, auth_color = auth_display(j["visa_status"])
        meta.badge(auth_label, icon=":material/verified_user:", color=auth_color)
        lang_label, lang_color = lang_display(j["country"], j["language_requirement"])
        meta.badge(lang_label, icon=":material/translate:", color=lang_color)
        meta.badge(f"CV: {j['recommended_cv']}", icon=":material/description:", color="gray")

        if j["llm_reasoning"]:
            st.caption(f":material/smart_toy: {j['llm_reasoning']}")
        if j["strengths"]:
            st.markdown(":green-badge[Strengths] " + " · ".join(j["strengths"].split("|")))
        if j["gaps"]:
            st.markdown(":orange-badge[Gaps] " + " · ".join(j["gaps"].split("|")))

        if j["llm_tailored_bullets"]:
            with st.expander("Suggested CV bullets for this job", icon=":material/description:"):
                for bullet in j["llm_tailored_bullets"].split("|"):
                    st.markdown(f"- {bullet}")

        if j["url"]:
            st.link_button("Open job posting", j["url"], icon=":material/open_in_new:")


def nav_css(selected):
    """Scoped styling for the right-hand market navigation (user-requested)."""
    rules = ["""
[class*="st-key-nav_"] button {
    justify-content: flex-start;
    text-align: left;
    padding: 0.65rem 0.9rem;
    border-radius: 0.55rem;
    border: 1px solid rgba(128, 128, 128, 0.2);
}
[class*="st-key-nav_"] button p { font-size: 1.02rem; font-weight: 600; }
"""]
    for name in MARKET_NAMES:
        rgb = MARKET_RGB.get(name, DEFAULT_RGB)
        sel = name == selected
        rules.append(f"""
.st-key-nav_{name} button {{
    background: rgba({rgb}, {0.24 if sel else 0.10});
    border-left: 4px solid rgb({rgb});
    {f'box-shadow: inset 0 0 0 2px rgb({rgb});' if sel else ''}
}}
.st-key-nav_{name} button:hover {{ background: rgba({rgb}, {0.32 if sel else 0.18}); }}
.st-key-nav_{name} button p {{ font-weight: {700 if sel else 600}; }}
""")
    return "<style>" + "\n".join(rules) + "</style>"


def render_nav():
    if st.session_state.get("market") not in MARKET_NAMES:
        st.session_state["market"] = MARKET_NAMES[0]

    st.markdown("#### Markets")
    for name in MARKET_NAMES:
        if st.button(
            f"{MARKET_LABELS[name]}  ·  {filtered_count(name)}",
            key=f"nav_{name}",
            icon=MARKET_ICONS[name],
            width="stretch",
        ):
            st.session_state["market"] = name

    # Emitted after the loop so the selected-state styling reflects a just-made click.
    st.markdown(nav_css(st.session_state["market"]), unsafe_allow_html=True)
    return st.session_state["market"]


def render_filters(country):
    with st.expander("Filters", icon=":material/tune:", expanded=True):
        minimum = st.slider("Minimum score", 0, 100, FILTER_DEFAULTS["min"], key=f"min_{country}")
        max_years = st.slider(
            "Max years of experience required", 0, 15, FILTER_DEFAULTS["yrs"], key=f"yrs_{country}",
            help="Hide roles that ask for more than this many years. 15 = no limit.",
        )
        hide_senior = st.toggle("Hide senior / lead titles", value=FILTER_DEFAULTS["snr"], key=f"snr_{country}")
        hide_native = st.toggle("Hide native-language roles", value=FILTER_DEFAULTS["nat"], key=f"nat_{country}")
    return minimum, max_years, hide_senior, hide_native


def render_listing(country, minimum, max_years, hide_senior, hide_native):
    st.badge(MARKET_LABELS[country], icon=MARKET_ICONS[country],
             color=MARKET_BADGE.get(country, "gray"))
    if country in MARKET_BLURB:
        st.caption(MARKET_BLURB[country])

    data = market_jobs(country)
    if not data:
        st.info(f"No {MARKET_LABELS[country]} jobs tracked yet.", icon=":material/inbox:")
        return

    kept, dropped = [], 0
    for j in data:
        verdict = passes(j, minimum, max_years, hide_senior, hide_native)
        if verdict is None:
            continue
        if verdict is False:
            dropped += 1
            continue
        kept.append(j)
    data = kept

    counts = {"APPLY": 0, "CONSIDER": 0, "SKIP": 0, "UNSCORED": 0}
    for j in data:
        counts[combined_verdict(j)] = counts.get(combined_verdict(j), 0) + 1

    st.markdown(
        f":green-badge[APPLY {counts['APPLY']}] "
        f":orange-badge[CONSIDER {counts['CONSIDER']}] "
        f":red-badge[SKIP {counts['SKIP']}] "
        f":gray-badge[UNSCORED {counts['UNSCORED']}]"
    )
    if dropped:
        st.caption(f"{dropped} role(s) hidden by the seniority / language filters.")

    if not data:
        st.info("No jobs match the current filters.", icon=":material/filter_alt:")
        return

    n_pages = max(1, math.ceil(len(data) / PER_PAGE))
    page_key = f"page_{country}"
    if st.session_state.get(page_key, 1) > n_pages:
        st.session_state[page_key] = 1

    start = (st.session_state.get(page_key, 1) - 1) * PER_PAGE
    page_jobs = data[start:start + PER_PAGE]
    st.caption(f"Showing {start + 1}–{start + len(page_jobs)} of {len(data)} jobs")

    for j in page_jobs:
        render_card(j)

    if n_pages > 1:
        with st.container(horizontal=True, horizontal_alignment="center"):
            st.pagination(n_pages, key=page_key)


st.title(":material/radar: Career Radar")
st.markdown(CARD_CSS, unsafe_allow_html=True)

main_col, aside_col = st.columns([3, 1], gap="large")

with aside_col:
    market = render_nav()
    active_filters = render_filters(market)

with main_col:
    render_listing(market, *active_filters)

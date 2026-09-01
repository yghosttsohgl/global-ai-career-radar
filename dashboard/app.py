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
# icon and one-line blurb differ.
MARKET_LABELS = {name: name for name in MARKET_NAMES}
MARKET_ICONS = {name: ":material/work:" for name in MARKET_NAMES}
MARKET_BLURB = {}

MARKET_LABELS["Vienna"] = "Part-time (local)"
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

# Market that gets a distinct, always-on accent in the navigation.
SPECIAL_MARKET = "Vienna"

init()
st.set_page_config(page_title="Global AI Career Radar", page_icon=":material/radar:", layout="wide")


@st.cache_data(ttl=300)
def all_jobs():
    return jobs()


@st.cache_data(ttl=300)
def market_totals():
    totals = {}
    for j in all_jobs():
        totals[j["country"]] = totals.get(j["country"], 0) + 1
    return totals


def combined_score(j):
    return j["llm_score"] if j["llm_score"] is not None else j["rule_score"]


def combined_verdict(j):
    return j["llm_verdict"] or j["recommendation"] or "UNSCORED"


def job_text(j):
    return f"{j['title']} {j['description'] or ''}"


def render_card(j):
    score = combined_score(j)
    verdict = combined_verdict(j)
    llm_scored = j["llm_score"] is not None
    years = required_years(job_text(j))
    senior = is_senior_title(j["title"])
    native = requires_native_language(j["country"], j["language_requirement"], job_text(j))

    with st.container(border=True):
        head = st.container(horizontal=True, vertical_alignment="center")
        head.markdown(f"### {round(score)}/100")
        head.markdown(f"**{j['title']}**")

        badges = st.container(horizontal=True)
        badges.badge(verdict, color=VERDICT_COLOR.get(verdict, "gray"))
        if llm_scored:
            badges.badge("AI-scored", icon=":material/smart_toy:", color="violet")
        else:
            badges.badge("Rule-scored", icon=":material/rule:", color="gray")
        if senior:
            badges.badge("Senior title", icon=":material/trending_up:", color="red")
        if years:
            badges.badge(f"{years}+ yrs wanted", icon=":material/schedule:",
                         color="red" if years > 3 else "gray")
        if native:
            badges.badge("Native language", icon=":material/translate:", color="red")

        st.caption(f"{j['company']} · {j['location'] or 'Location unknown'} · {j['country']}")

        lang_label = LANG_LABEL.get(j["country"], "Local language")
        st.markdown(
            f"**Authorization:** {j['visa_status']} &nbsp;·&nbsp; "
            f"**{lang_label}:** {j['language_requirement']} &nbsp;·&nbsp; "
            f"**Suggested CV:** {j['recommended_cv']}"
        )

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
    return f"""
<style>
[class*="st-key-nav_"] button {{
    justify-content: flex-start;
    text-align: left;
    padding: 0.7rem 0.9rem;
    border-radius: 0.6rem;
}}
[class*="st-key-nav_"] button p {{
    font-size: 1.03rem;
    font-weight: 600;
}}
/* currently selected market */
.st-key-nav_{selected} button {{
    box-shadow: inset 0 0 0 2px #3b82f6;
}}
.st-key-nav_{selected} button p {{
    font-weight: 700;
}}
/* the stand-out "{MARKET_LABELS[SPECIAL_MARKET]}" entry, in every state */
.st-key-nav_{SPECIAL_MARKET} button {{
    border-left: 4px solid #e8871e;
    background: rgba(232, 135, 30, 0.13);
}}
.st-key-nav_{SPECIAL_MARKET} button:hover {{
    background: rgba(232, 135, 30, 0.22);
}}
</style>
"""


def render_nav():
    if st.session_state.get("market") not in MARKET_NAMES:
        st.session_state["market"] = MARKET_NAMES[0]

    totals = market_totals()
    st.markdown("#### Markets")
    for name in MARKET_NAMES:
        if st.button(
            f"{MARKET_LABELS[name]}  ·  {totals.get(name, 0)}",
            key=f"nav_{name}",
            icon=MARKET_ICONS[name],
            width="stretch",
        ):
            st.session_state["market"] = name

    # Emitted after the loop so the selected-state ring reflects a just-made click.
    st.markdown(nav_css(st.session_state["market"]), unsafe_allow_html=True)
    return st.session_state["market"]


def render_filters(country):
    with st.expander("Filters", icon=":material/tune:", expanded=True):
        minimum = st.slider("Minimum score", 0, 100, 40, key=f"min_{country}")
        max_years = st.slider(
            "Max years of experience required", 0, 15, CANDIDATE_YEARS, key=f"yrs_{country}",
            help="Hide roles that ask for more than this many years. 15 = no limit.",
        )
        hide_senior = st.toggle("Hide senior / lead titles", value=True, key=f"snr_{country}")
        hide_native = st.toggle("Hide native-language roles", value=True, key=f"nat_{country}")
    return minimum, max_years, hide_senior, hide_native


def render_listing(country, minimum, max_years, hide_senior, hide_native):
    st.header(MARKET_LABELS[country], anchor=False)
    if country in MARKET_BLURB:
        st.caption(MARKET_BLURB[country])

    data = [j for j in all_jobs() if j["country"] == country]
    if not data:
        st.info(f"No {MARKET_LABELS[country]} jobs tracked yet.", icon=":material/inbox:")
        return

    kept, dropped = [], 0
    for j in data:
        if combined_score(j) < minimum:
            continue
        text = job_text(j)
        if max_years < 15 and required_years(text) > max_years:
            dropped += 1
            continue
        if hide_senior and is_senior_title(j["title"]):
            dropped += 1
            continue
        if hide_native and requires_native_language(j["country"], j["language_requirement"], text):
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


st.title(":material/radar: Global AI Career Radar")

main_col, aside_col = st.columns([3, 1], gap="large")

with aside_col:
    market = render_nav()
    active_filters = render_filters(market)

with main_col:
    render_listing(market, *active_filters)

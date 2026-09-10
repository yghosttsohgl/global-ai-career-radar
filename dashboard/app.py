import math
import re
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

import streamlit as st

from radar.config import scoring as scoring_config
from radar.db import init, jobs, save, set_application_status
from radar.importer import fetch_posting, import_job, parse_posting
from radar.scoring import is_senior_title, required_years, requires_native_language

PER_PAGE = 10
VERDICT_COLOR = {"APPLY": "green", "CONSIDER": "orange", "SKIP": "red", "UNSCORED": "gray"}

# Hand-tracked application status. "" = untouched; kept short and ordered roughly
# by pipeline stage. STATUS_COLOR feeds the on-card badge.
STATUS_OPTIONS = ["", "Interested", "Applied", "Interviewing", "Offer", "Rejected", "Not considered"]
STATUS_COLOR = {
    "Interested": "blue",
    "Applied": "green",
    "Interviewing": "violet",
    "Offer": "green",
    "Rejected": "red",
    "Not considered": "gray",
}
STATUS_ICON = {
    "Interested": ":material/star:",
    "Applied": ":material/send:",
    "Interviewing": ":material/forum:",
    "Offer": ":material/celebration:",
    "Rejected": ":material/block:",
    "Not considered": ":material/do_not_disturb_on:",
}

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

FILTER_DEFAULTS = {"min": 40, "yrs": CANDIDATE_YEARS, "snr": True, "nat": True,
                   "status": "All", "hnc": True, "happ": True, "hint": True}
STATUS_FILTER_OPTIONS = ["All", "Unset"] + STATUS_OPTIONS[1:]

# Pinned pseudo-markets: pools that sit above the real markets in the nav.
# "Interested" gathers every hand-tagged role; "Imported" gathers jobs added by
# hand (source = "Manual import"). Both group their contents by market.
INTERESTED_VIEW = "Interested"
IMPORTED_VIEW = "Imported"
PINNED_VIEWS = (INTERESTED_VIEW, IMPORTED_VIEW)

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
        "PREFERRED_OR_CONVERSATIONAL": (f"{lang} expected (B1/B2 ok)", "gray"),
        "BUSINESS_OR_HIGHER": (f"Near-native {lang} required", "orange"),
        "UNKNOWN": (f"{lang} requirement unclear", "gray"),
    }.get(requirement, (str(requirement).replace("_", " ").capitalize(), "gray"))


# Section headings that usually start / end the "what we want from you" block.
# Matched as lowercase substrings of the (space-joined) posting text. Strong
# headings are tried first; the vaguer weak ones only if nothing strong hits.
_REQ_STRONG = [
    "ihr profil", "dein profil", "ihr anforderungsprofil", "dein anforderungsprofil",
    "anforderungsprofil", "unsere anforderungen", "was sie mitbringen", "was du mitbringst",
    "das bringen sie mit", "das bringst du mit", "das solltest du mitbringen",
    "womit du uns überzeugst", "das zeichnet dich aus", "ihre qualifikation",
    "deine qualifikation", "ihre fähigkeiten", "wen wir suchen", "das erwarten wir",
    "fachliche qualifikation", "damit begeisterst du uns", "das erwarten wir uns",
    "your profile", "who you are", "what you'll need", "what you will need",
    "what you bring", "what you will bring", "minimum qualifications", "basic qualifications",
    "required experience", "what we're looking for", "what we are looking for",
    "you may be a good fit if", "about you", "skills and experience",
    "skills and experiences", "experience and qualifications", "you should have",
    "you'll bring", "must-have", "must haves", "we're looking for", "we are looking for",
    "応募資格", "応募必要条件", "必須スキル", "必須条件", "必須要件", "必要な経験",
    "求める経験", "求めるスキル", "求める人物像", "スキル・経験",
]
_REQ_WEAK = ["requirements", "qualifications", "voraussetzungen", "anforderungen"]
_STOP_HEADINGS = [
    "benefits", "we offer", "what we offer", "was wir bieten", "wir bieten",
    "unser angebot", "deine benefits", "das bieten wir", "your benefits",
    "about us", "über uns", "about the company", "how to apply", "das erwartet dich",
    "unsere brüller", "perks", "compensation", "salary", "gehalt", "wir freuen uns",
    "über das unternehmen", "das spricht dich an", "detaillierte angaben zur stelle",
    "待遇", "福利厚生", "選考", "勤務地", "給与", "歓迎スキル",
]


_BULLET_CHARS = " \t-–—·•●▪*›»◦"


def desc_lines(desc):
    """Posting text as a list of trimmed, de-bulleted, de-duplicated lines."""
    out, seen = [], set()
    for raw in (desc or "").splitlines():
        line = raw.strip(_BULLET_CHARS).strip()
        if len(line) < 2:
            continue
        key = line.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(line)
    return out


def requirements_lines(desc, max_items=16):
    """Best-effort list of requirement bullet lines from a posting."""
    if not desc:
        return []
    low = desc.lower()
    hits = [i for i in (low.find(h) for h in _REQ_STRONG) if i >= 0]
    if not hits:
        hits = [i for i in (low.find(h) for h in _REQ_WEAK) if i >= 0]
    if not hits:
        return []
    start = min(hits)
    rest = low[start + 15:]
    stops = [i for i in (rest.find(h) for h in _STOP_HEADINGS) if i >= 0]
    end = start + 15 + min(stops) if stops else start + 2400
    chunk = desc[start:end]

    lines = desc_lines(chunk)
    if lines and len(lines[0]) < 45:  # drop the heading itself
        lines = lines[1:]
    if len(lines) <= 1:  # flat blob (older data) - split on sentence / list punctuation
        blob = re.sub(r"\s+", " ", chunk).strip(_BULLET_CHARS)
        lines = [p.strip() for p in re.split(r"(?<=[.!?;:])\s+|\s[•·▪●]\s", blob) if len(p.strip()) > 3]
        if lines and len(lines[0]) < 45:
            lines = lines[1:]
    return lines[:max_items]


def filter_values(country):
    """The market's current filter settings (its widget state, or the defaults)."""
    return (
        st.session_state.get(f"min_{country}", FILTER_DEFAULTS["min"]),
        st.session_state.get(f"yrs_{country}", FILTER_DEFAULTS["yrs"]),
        st.session_state.get(f"snr_{country}", FILTER_DEFAULTS["snr"]),
        st.session_state.get(f"nat_{country}", FILTER_DEFAULTS["nat"]),
        st.session_state.get(f"status_filter_{country}", FILTER_DEFAULTS["status"]),
        st.session_state.get(f"hnc_{country}", FILTER_DEFAULTS["hnc"]),
        st.session_state.get(f"happ_{country}", FILTER_DEFAULTS["happ"]),
        st.session_state.get(f"hint_{country}", FILTER_DEFAULTS["hint"]),
    )


def status_ok(j, status_filter):
    s = j["application_status"] or ""
    if status_filter == "All":
        return True
    if status_filter == "Unset":
        return s == ""
    return s == status_filter


def passes(j, minimum, max_years, hide_senior, hide_native, status_filter,
           hide_not_considered, hide_applied, hide_interested):
    s = j["application_status"] or ""
    # Rejected jobs drop out of every view unless you explicitly filter to them.
    if s == "Rejected" and status_filter != "Rejected":
        return None
    if s == "Not considered" and hide_not_considered and status_filter != "Not considered":
        return None
    if s == "Applied" and hide_applied and status_filter != "Applied":
        return None
    # 'Interested' roles live in the pinned pool; keep them out of the per-market
    # listings by default (toggle off, or filter status to 'Interested', to see them).
    if s == "Interested" and hide_interested and status_filter != "Interested":
        return None
    if not status_ok(j, status_filter):
        return None
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


def interested_jobs():
    """Every role hand-tagged 'Interested' (any market), in DB order."""
    return [j for j in all_jobs() if (j["application_status"] or "") == "Interested"]


def imported_jobs():
    """Every hand-imported job (source = 'Manual import'), in DB order."""
    return [j for j in all_jobs() if j["source"] == "Manual import"]


def filtered_count(country):
    vals = filter_values(country)
    return sum(1 for j in market_jobs(country) if passes(j, *vals) is True)


def _set_status(fingerprint):
    set_application_status(fingerprint, st.session_state.get(f"status_{fingerprint}", ""))
    all_jobs.clear()


def _card_style(fingerprint, status, country=None):
    """Per-card scoped CSS: highlight 'Interested' in the market's accent colour
    (purple Japan / blue Austria / teal Remote / amber Vienna), dim 'Not considered'."""
    sel = f".st-key-jobcard_{fingerprint}"
    if status == "Interested":
        rgb = MARKET_RGB.get(country, DEFAULT_RGB)
        return (
            f"<style>{sel}, {sel} [data-testid=\"stVerticalBlockBorderWrapper\"] {{"
            f"border: 2px solid rgb({rgb}) !important; border-radius: 0.6rem;"
            f"background: rgba({rgb}, 0.07);"
            f"box-shadow: 0 1px 10px rgba({rgb}, 0.20); }}</style>"
        )
    if status == "Not considered":
        return f"<style>{sel} {{ opacity: 0.45; filter: grayscale(0.85); }}</style>"
    return ""


def render_card(j, show_req=False):
    fp = j["fingerprint"]
    score = combined_score(j)
    verdict = combined_verdict(j)
    llm_scored = j["llm_score"] is not None
    years = required_years(job_text(j))
    senior = is_senior_title(j["title"])
    native = requires_native_language(j["country"], j["language_requirement"], job_text(j))
    status = j["application_status"] or ""

    score_color = VERDICT_COLOR.get(verdict, "gray")

    style = _card_style(fp, status, j["country"])
    if style:
        st.html(style)

    with st.container(border=True, key=f"jobcard_{fp}"):
        top = st.columns([3, 1], vertical_alignment="center")
        top[0].markdown(f"### {j['title']}")
        skey = f"status_{fp}"
        if skey not in st.session_state:
            st.session_state[skey] = status
        top[1].selectbox(
            "Application status", STATUS_OPTIONS, key=skey,
            on_change=_set_status, args=(fp,),
            format_func=lambda s: s or "Set status…",
            label_visibility="collapsed",
        )

        badges = st.container(horizontal=True, vertical_alignment="center")
        badges.badge(verdict, color=score_color)
        if llm_scored:
            badges.badge("AI-scored", icon=":material/smart_toy:", color="violet")
        else:
            badges.badge("Rule-scored", icon=":material/rule:", color="gray")
        badges.markdown(f":{score_color}[**{round(score)}%**]")
        if status:
            badges.badge(status, icon=STATUS_ICON.get(status), color=STATUS_COLOR.get(status, "gray"))
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
        if j["recommended_cv"]:  # blank for markets with match_cv: false (e.g. Vienna)
            meta.badge(f"CV: {j['recommended_cv']}", icon=":material/description:", color="gray")

        if j["llm_reasoning"]:
            st.caption(f":material/smart_toy: {j['llm_reasoning']}")
        if j["strengths"]:
            st.markdown(":green-badge[Strengths] " + " · ".join(j["strengths"].split("|")))
        if j["gaps"]:
            st.markdown(":orange-badge[Gaps] " + " · ".join(j["gaps"].split("|")))

        if show_req and j["description"]:
            req = requirements_lines(j["description"])
            all_lines = desc_lines(j["description"])
            with st.container(border=True):
                if req:
                    st.caption("Requirements — extracted from the posting")
                    st.markdown("\n".join(f"- {line}" for line in req))
                else:
                    st.caption("Posting text — no requirements section detected")
                    st.markdown("\n".join(f"- {line}" for line in all_lines[:12]) or "_none saved_")
            with st.expander("Full posting text", icon=":material/article:"):
                st.markdown("\n\n".join(all_lines) or "_none saved_")

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

    for key, rgb, view in (("interested", "37,99,235", INTERESTED_VIEW),
                           ("imported", "22,163,74", IMPORTED_VIEW)):
        on = selected == view
        rules.append(f"""
.st-key-nav_{key} button {{
    background: rgba({rgb}, {0.24 if on else 0.10});
    border-left: 4px solid rgb({rgb});
    {f'box-shadow: inset 0 0 0 2px rgb({rgb});' if on else ''}
}}
.st-key-nav_{key} button:hover {{ background: rgba({rgb}, {0.32 if on else 0.18}); }}
.st-key-nav_{key} button p {{ font-weight: {700 if on else 600}; }}
""")
    return "<style>" + "\n".join(rules) + "</style>"


def render_nav():
    if st.session_state.get("market") not in (*MARKET_NAMES, *PINNED_VIEWS):
        st.session_state["market"] = MARKET_NAMES[0]

    st.markdown("#### Pinned")
    if st.button(
        f"Interested  ·  {len(interested_jobs())}",
        key="nav_interested",
        icon=":material/star:",
        width="stretch",
    ):
        st.session_state["market"] = INTERESTED_VIEW
    if st.button(
        f"Imported  ·  {len(imported_jobs())}",
        key="nav_imported",
        icon=":material/note_add:",
        width="stretch",
    ):
        st.session_state["market"] = IMPORTED_VIEW

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
        hide_nc = st.toggle("Hide 'Not considered' roles", value=FILTER_DEFAULTS["hnc"], key=f"hnc_{country}")  # hidden by default
        hide_app = st.toggle(
            "Hide 'Applied' roles", value=FILTER_DEFAULTS["happ"], key=f"happ_{country}",  # hidden by default
            help="Drop roles you've already applied to. Turn off to review them.",
        )
        hide_int = st.toggle(
            "Hide 'Interested' roles", value=FILTER_DEFAULTS["hint"], key=f"hint_{country}",  # hidden by default
            help="Interested roles live in the pinned Interested pool. Turn off to see them in this market's list too.",
        )
        status_filter = st.selectbox(
            "Application status", STATUS_FILTER_OPTIONS,
            format_func=lambda s: s or "Set status…", key=f"status_filter_{country}",
        )
        show_req = st.toggle(
            "Show requirements", value=False, key=f"req_{country}",
            help="Show each posting's requirements section (and full text) on the card.",
        )
    return (minimum, max_years, hide_senior, hide_native, status_filter,
            hide_nc, hide_app, hide_int, show_req)


def render_listing(country, minimum, max_years, hide_senior, hide_native,
                   status_filter, hide_nc, hide_app, hide_int, show_req):
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
        verdict = passes(j, minimum, max_years, hide_senior, hide_native, status_filter,
                         hide_nc, hide_app, hide_int)
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
        render_card(j, show_req)

    if n_pages > 1:
        with st.container(horizontal=True, horizontal_alignment="center"):
            st.pagination(n_pages, key=page_key)


def render_interested_pool(show_req=False):
    """The pinned 'Interested' pool: every hand-tagged role, grouped by market.

    Deliberately ignores the score / seniority / language filters - a role is
    here because it was explicitly shortlisted. Change a card's status to drop
    it back out.
    """
    st.badge("Interested", icon=":material/star:", color="blue")
    st.caption(
        "Every role tagged 'Interested', grouped by market. Change a role's "
        "status on its card to add or remove it here."
    )

    data = interested_jobs()
    if not data:
        st.info(
            "No roles tagged 'Interested' yet. Set a role's status to "
            "'Interested' on its card to build the pool.",
            icon=":material/star:",
        )
        return

    groups = [(name, [j for j in data if j["country"] == name]) for name in MARKET_NAMES]
    groups = [(name, js) for name, js in groups if js]
    other = [j for j in data if j["country"] not in MARKET_NAMES]

    summary = "  ·  ".join(f"{MARKET_LABELS[name]} {len(js)}" for name, js in groups)
    if other:
        summary += f"  ·  Other {len(other)}"
    st.markdown(f"**{len(data)} role(s)** &nbsp;—&nbsp; {summary}")

    for name, js in groups:
        st.divider()
        st.badge(f"{MARKET_LABELS[name]}  ·  {len(js)}", icon=MARKET_ICONS[name],
                 color=MARKET_BADGE.get(name, "gray"))
        for j in sorted(js, key=combined_score, reverse=True):
            render_card(j, show_req)

    if other:
        st.divider()
        st.badge(f"Other  ·  {len(other)}", icon=":material/help:", color="gray")
        for j in sorted(other, key=combined_score, reverse=True):
            render_card(j, show_req)


def _import_form():
    """The 'add a job' form for the Imported pool. Paste the whole posting (or the
    page it's on) and hit Parse to split it into Title / Company / Market / text -
    or fetch a URL - then correct and import. Rule-scored on save; picked up by
    the next LLM scoring run regardless of score."""
    seed = st.session_state.get("imp_seed", {})

    with st.expander("Add a job", icon=":material/note_add:",
                     expanded=not imported_jobs()):
        paste_tab, url_tab = st.tabs(["Paste text", "From URL"])
        with paste_tab:
            blob = st.text_area(
                "Paste the whole job posting (or the page it's on)", key="imp_blob", height=150,
                placeholder="Select-all on the posting, copy, paste here — then Parse",
            )
            if st.button("Parse", key="imp_parse_btn", icon=":material/auto_fix_high:",
                         disabled=not blob.strip()):
                st.session_state["imp_seed"] = parse_posting(blob, MARKET_NAMES)
                st.rerun()
        with url_tab:
            url = st.text_input("Job URL", key="imp_url", placeholder="https://…")
            if st.button("Fetch details", key="imp_fetch_btn", icon=":material/download:",
                         disabled=not url.strip()):
                res = fetch_posting(url)
                if res.get("error"):
                    st.warning(f"Couldn't fetch that page ({res['error']}). "
                               "Paste the posting text instead.", icon=":material/warning:")
                else:
                    st.session_state["imp_seed"] = res
                    st.rerun()

        if seed.get("hint"):
            st.warning(seed["hint"], icon=":material/info:")
        st.caption("Check the parsed fields below before importing.")
        with st.form("import_job", border=False):
            c1, c2 = st.columns([3, 2])
            title = c1.text_input("Title", value=seed.get("title", ""))
            company = c2.text_input("Company", value=seed.get("company", ""))
            guess = seed.get("market")
            idx = (MARKET_NAMES.index(guess) if guess in MARKET_NAMES
                   else MARKET_NAMES.index("Remote") if "Remote" in MARKET_NAMES else 0)
            country = st.selectbox("Market", MARKET_NAMES, index=idx,
                                   format_func=lambda m: MARKET_LABELS[m])
            description = st.text_area("Posting text", value=seed.get("description", ""),
                                       height=220, placeholder="The full job description")
            submitted = st.form_submit_button("Import job", icon=":material/add:", type="primary")

        if submitted:
            if not title.strip():
                st.error("A title is required.")
            else:
                j = import_job(title=title, company=company, country=country,
                               description=description,
                               url=seed.get("url") or st.session_state.get("imp_url", ""))
                save(j)
                for k in ("imp_seed", "imp_blob", "imp_url"):
                    st.session_state.pop(k, None)
                all_jobs.clear()
                st.success(f"Imported **{j.title}** into {MARKET_LABELS[country]}. "
                           "It'll get an AI verdict on the next scoring run.",
                           icon=":material/check_circle:")
                st.rerun()


def render_imported_pool(show_req=False):
    """The pinned 'Imported' pool: hand-added jobs, grouped by market. Ignores the
    score / seniority / language filters - you imported these on purpose."""
    st.badge("Imported", icon=":material/note_add:", color="green")
    st.caption(
        "Jobs you added by hand (from a link or pasted text), grouped by market. "
        "Each is rule-scored on import and picked up by the next AI scoring run."
    )

    _import_form()

    data = imported_jobs()
    if not data:
        return

    groups = [(name, [j for j in data if j["country"] == name]) for name in MARKET_NAMES]
    groups = [(name, js) for name, js in groups if js]
    other = [j for j in data if j["country"] not in MARKET_NAMES]

    summary = "  ·  ".join(f"{MARKET_LABELS[name]} {len(js)}" for name, js in groups)
    if other:
        summary += f"  ·  Other {len(other)}"
    st.markdown(f"**{len(data)} imported job(s)** &nbsp;—&nbsp; {summary}")

    for name, js in groups:
        st.divider()
        st.badge(f"{MARKET_LABELS[name]}  ·  {len(js)}", icon=MARKET_ICONS[name],
                 color=MARKET_BADGE.get(name, "gray"))
        for j in sorted(js, key=combined_score, reverse=True):
            render_card(j, show_req)

    if other:
        st.divider()
        st.badge(f"Other  ·  {len(other)}", icon=":material/help:", color="gray")
        for j in sorted(other, key=combined_score, reverse=True):
            render_card(j, show_req)


st.title(":material/radar: Career Radar")

main_col, aside_col = st.columns([3, 1], gap="large")

with aside_col:
    market = render_nav()
    active_filters = render_filters(market) if market not in PINNED_VIEWS else None

with main_col:
    if market == INTERESTED_VIEW:
        render_interested_pool()
    elif market == IMPORTED_VIEW:
        render_imported_pool()
    else:
        render_listing(market, *active_filters)

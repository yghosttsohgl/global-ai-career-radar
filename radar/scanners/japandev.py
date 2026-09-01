"""japan-dev.com - English-friendly Japan tech jobs (public JSON API).

No per-job description in the API, so we synthesise one from the structured
fields (company blurb, skills, Japanese level, remote level, salary).
"""
from . import ENDPOINTS, _keeps, fetch, make_job, register
from ..db import save

JAPANESE_LEVEL_LABELS = {
    "japanese_level_none": "no Japanese required",
    "japanese_level_beginner": "beginner Japanese",
    "japanese_level_conversational": "conversational Japanese",
    "japanese_level_business_level": "business-level Japanese",
    "japanese_level_fluent": "fluent/native Japanese",
}


@register("japandev")
def scan(s):
    title_filter = [x.lower() for x in s.get("title_filter", [])]
    jobs_data = fetch(ENDPOINTS["japandev_jobs"]).json().get("data", [])
    companies = fetch(ENDPOINTS["japandev_companies"]).json().get("data", [])
    blurbs = {c["id"]: (c["attributes"].get("description") or "").strip() for c in companies}

    saved = 0
    for row in jobs_data:
        a = row["attributes"]
        if a.get("is_japanese_only") or not _keeps(a["title"], title_filter):
            continue
        company = a.get("company") or {}
        skills = ", ".join(sk["name"] for sk in a.get("skills") or [])
        jp = JAPANESE_LEVEL_LABELS.get(a.get("japanese_level_enum"), a.get("japanese_level") or "unspecified")
        salary = ""
        if a.get("salary_min") and a.get("salary_max"):
            salary = f" Salary: {a['salary_min']:,}-{a['salary_max']:,} JPY."
        description = (
            f"{a['title']} at {company.get('name', 'a company')}. "
            f"{blurbs.get(str(company.get('id')), '')} "
            f"Location: {a.get('location') or 'Japan'}. Japanese level: {jp}. "
            f"Remote: {(a.get('remote_level') or '').replace('remote_level_', '') or 'unspecified'}. "
            f"Skills: {skills or 'n/a'}.{salary}"
        ).strip()
        url = a.get("application_url") or (
            f"https://japan-dev.com/jobs/{company.get('slug')}/{a['slug']}"
            if company.get("slug") else "https://japan-dev.com/jobs"
        )
        save(make_job(
            title=a["title"], company=company.get("name") or s["name"],
            country=s["country"], location=a.get("location") or "Japan",
            url=url, source=s["name"], description=description,
        ))
        saved += 1
    return saved

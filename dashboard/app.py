import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parents[1]))
import streamlit as st
from radar.db import init,jobs,save
from radar.importer import import_job

init()
st.set_page_config(page_title="Global AI Career Radar",layout="wide")
st.title("🌍 Global AI Career Radar")

a,b,c=st.tabs(["Ranked Jobs","Manual Import","Profile"])

with a:
    data=jobs()
    countries=st.multiselect("Countries",["Japan","Austria","China"],["Japan","Austria","China"])
    minimum=st.slider("Minimum score",0,100,40)
    st.info("Japan: JLPT N1 (2018); strong reading/listening, weak speaking/writing. Austria: unrestricted work permit. China: Mandarin native; work authorization requires verification.")
    for j in data:
        score = j["llm_score"] if j["llm_score"] is not None else j["rule_score"]
        verdict = j["llm_verdict"] or j["recommendation"] or "UNSCORED"
        if j["country"] not in countries or score < minimum: continue
        badge = "🤖" if j["llm_score"] is not None else "📏"
        st.subheader(f'{badge} {round(score)}/100 — {j["title"]}')
        st.write(f'**{j["company"]}** · {j["location"] or "Unknown"} · {j["country"]}')
        st.write(f'Authorization: **{j["visa_status"]}** · Japanese: **{j["japanese_requirement"]}**')
        st.write(f'Recommended CV: **{j["recommended_cv"]}** · Recommendation: **{verdict}**')
        if j["llm_reasoning"]: st.caption(f'🤖 {j["llm_reasoning"]}')
        if j["strengths"]: st.caption("✅ " + " · ".join(j["strengths"].split("|")))
        if j["gaps"]: st.caption("⚠️ " + " · ".join(j["gaps"].split("|")))
        if j["llm_tailored_bullets"]:
            with st.expander("Suggested CV bullets for this job"):
                for bullet in j["llm_tailored_bullets"].split("|"): st.write(f"- {bullet}")
        if j["url"]: st.link_button("Open job",j["url"])
        st.divider()

with b:
    st.header("Manual Job Import")
    st.write("Use this for BOSS直聘 or other login-only sources you can access normally. Do not bypass login, CAPTCHA, or anti-bot controls.")
    with st.form("import"):
        title=st.text_input("Job title")
        company=st.text_input("Company")
        country=st.selectbox("Country",["China","Japan","Austria"])
        location=st.text_input("Location")
        url=st.text_input("URL")
        desc=st.text_area("Paste visible job description / requirements",height=300)
        ok=st.form_submit_button("Analyze and save")
    if ok and title and desc:
        j=import_job(title,company,country,location,url,desc)
        save(j)
        st.success(f"Saved: {j.title} — {round(j.rule_score)}/100")
        st.write(f"Recommended CV: **{j.recommended_cv}**")
        st.write(f"Recommendation: **{j.recommendation}**")

with c:
    st.header("Master Profile")
    st.write("Edit profile/master_profile.yaml to add projects, skills and experience.")
    st.write("Edit profile/cv_versions.yaml to control CV versions.")

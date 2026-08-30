import yaml

with open("profile/master_profile.yaml", encoding="utf8") as f:
    PROFILE = yaml.safe_load(f)

# (label, keywords, points). Label is stored in Job.strengths when matched.
# The candidate's toolkit is broader than AI - QA/testing, Salesforce/CRM,
# software dev, product/program/project management, data, operations and
# localization all count. Points can stack; a solid non-AI match should still
# clear RULE_SCORE_FLOOR (40 in llm_scoring.py) and reach the LLM pass.
KEYWORD_GROUPS = [
    ("AI / GenAI / NLP / ML", [
        "llm", "genai", "generative ai", "machine learning", "ml engineer", "nlp",
        "大模型", "大语言模型", "人工智能", "自然语言",
    ], 22),
    ("AI model evaluation / quality", [
        "model evaluation", "model quality", "ai quality", "benchmark", "eval harness",
        "评测", "模型评估", "模型效果",
    ], 15),
    ("Speech (TTS / ASR)", [
        "tts", "asr", "speech", "voice", "语音", "语音识别", "语音合成",
    ], 12),
    ("QA / Testing / Test automation", [
        "qa engineer", "quality assurance", "test engineer", "sdet", "test automation",
        "manual testing", "automated test", "integration test", "unit test", "api testing",
        "end-to-end test", "e2e test", "playwright", "selenium", "cypress", "postman",
        "test case", "test plan", "测试", "质量保证",
    ], 25),
    ("Salesforce / CRM / low-code", [
        "salesforce", "apex", "lightning", "sales cloud", "service cloud", "mulesoft",
        "low-code", "no-code", "dynamics 365", "crm platform", "crm developer",
        "crm administrator", "hubspot",
    ], 25),
    ("Software engineering", [
        "software engineer", "software developer", "backend", "front-end", "frontend",
        "full stack", "full-stack", "web developer", "python", "javascript", "typescript",
        "rest api", "sql", "git ",
    ], 18),
    ("Product / Program / Project management", [
        "product manager", "product owner", "technical product", "program manager",
        "project manager", "delivery manager", "scrum master", "project lead",
        "产品经理", "项目经理", "项目管理", "プロジェクトマネージャ", "プロダクトマネージャ",
    ], 18),
    ("Data (analysis / quality / annotation)", [
        "data analyst", "data engineer", "data quality", "analytics", "business intelligence",
        "dashboard", "etl", "data pipeline", "annotation", "data labeling", "labelling",
        "数据分析", "数据标注",
    ], 15),
    ("Operations / Business operations", [
        "operations manager", "business operations", "revops", "bizops", "sales operations",
        "process improvement", "process automation", "workflow automation", "business process",
        "operational excellence", "运营", "业务运营",
    ], 15),
    ("Localization / i18n / linguistic", [
        "localization", "localisation", "i18n", "l10n", "internationalization",
        "translation", "linguist", "machine translation", "language quality", "transcreation",
        "本地化", "ローカライズ",
    ], 20),
    ("DevOps / Cloud", [
        "devops", "kubernetes", "docker", "aws", "gcp", "azure", "ci/cd", "terraform",
        "cloud engineer", "site reliability",
    ], 12),
    ("Agile tooling / process", [
        "jira", "confluence", "agile", "scrum", "kanban",
    ], 6),
    ("English-friendly / international team", [
        "english", "international team", "english is the working language", "英文",
    ], 10),
    ("Visa sponsorship / relocation mentioned", [
        "visa sponsorship", "visa support", "work visa", "relocation support",
        "relocation package", "签证", "工作许可", "工作签证",
    ], 15),
    ("Multilingual asset (JP / ZH / EN / DE)", [
        "bilingual", "trilingual", "mandarin", "chinese language", "japanese language",
        "german language", "日本語", "中文", "deutsch",
    ], 8),
]


def score(j):
    """Keyword-rule score for a job. Returns (score, matched_strength_labels)."""
    t = f"{j.title} {j.company} {j.description}".lower()
    total = 0
    strengths = []
    for label, keys, pts in KEYWORD_GROUPS:
        if any(k in t for k in keys):
            total += pts
            strengths.append(label)
    if j.country == "Austria":
        total += 5
        strengths.append("Austria: no visa required")
    if j.country == "China" and any(k in t for k in ["baidu", "百度", "大模型", "产品经理"]):
        total += 10
        strengths.append("China: matches Baidu/LLM PM background")
    return min(total, 100), strengths


def classify(j):
    """Fill in visa/language/authorization fields and note concrete gaps."""
    t = f"{j.title} {j.description}".lower()
    gaps = []

    if j.country == "Austria":
        j.visa_status = "NOT_NEEDED_FOR_USER"
    elif j.country == "Japan":
        if any(k in t for k in ["visa sponsorship", "visa support", "work visa support"]):
            j.visa_status = "CONFIRMED"
        else:
            j.visa_status = "UNKNOWN"
            gaps.append("Visa sponsorship not mentioned - verify before applying")
    else:
        j.visa_status = "UNKNOWN"
        j.china_work_authorization = "UNKNOWN"
        gaps.append("China work authorization not confirmed - verify before applying")

    j.language_requirement = _language_requirement(j.country, t, gaps)
    j.gaps = gaps
    return j


# Per-market local-language screen. The candidate has weak spoken/written
# Japanese (JLPT N1 reading only), German at B1 heading to B2, and native
# Mandarin - so a hard requirement is a real gap for Japan and Austria but
# essentially never for China.
_LANG_CUES = {
    "Japan": {
        "BUSINESS_OR_HIGHER": ["native japanese", "business japanese", "business-level japanese",
                               "fluent japanese", "jlpt n1", "商务日语", "日语n1", "ビジネスレベルの日本語"],
        "PREFERRED_OR_CONVERSATIONAL": ["japanese preferred", "conversational japanese",
                                        "日语优先", "日语加分", "日常会話レベル"],
        "ENGLISH_FRIENDLY": ["no japanese required", "english only", "english is the working language",
                             "英文工作", "no japanese ability required"],
        "gap": "Requires business-level+ Japanese; current speaking/writing is weak",
    },
    "Austria": {
        "BUSINESS_OR_HIGHER": ["verhandlungssicher", "fließend deutsch", "fliessend deutsch",
                               "sehr gute deutschkenntnisse", "ausgezeichnete deutschkenntnisse",
                               "muttersprache deutsch", "deutsch auf muttersprachniveau",
                               "c1 deutsch", "deutsch c1", "c2 deutsch", "deutsch c2",
                               "fluent german", "native german", "excellent german", "business-level german"],
        "PREFERRED_OR_CONVERSATIONAL": ["gute deutschkenntnisse", "deutschkenntnisse von vorteil",
                                        "grundkenntnisse deutsch", "deutsch erwünscht", "deutsch von vorteil",
                                        "b2 deutsch", "deutsch b2", "german is a plus", "conversational german"],
        "ENGLISH_FRIENDLY": ["english is the working language", "englisch als arbeitssprache",
                             "no german required", "german not required", "kein deutsch erforderlich",
                             "english-speaking team", "no german skills required"],
        "gap": "Requires business-level+ German; candidate is B1 (targeting B2)",
    },
}


def _language_requirement(country, text, gaps):
    cues = _LANG_CUES.get(country)
    if not cues:  # China - native Mandarin, no local-language barrier
        return "NOT_A_BARRIER_FOR_USER"
    for level in ("BUSINESS_OR_HIGHER", "PREFERRED_OR_CONVERSATIONAL", "ENGLISH_FRIENDLY"):
        if any(k in text for k in cues[level]):
            if level == "BUSINESS_OR_HIGHER":
                gaps.append(cues["gap"])
            return level
    return "UNKNOWN"


def cv(j):
    t = f"{j.title} {j.description}".lower()
    if j.country == "China" or any(x in t for x in ["baidu", "百度", "大模型"]):
        return "AI / LLM Product" if any(x in t for x in ["product", "产品", "manager", "经理"]) else "China-focused"
    if any(x in t for x in ["evaluation", "nlp", "speech", "tts", "asr", "machine translation", "localization", "localisation", "linguist"]):
        return "AI / NLP / Evaluation"
    if any(x in t for x in [
        "salesforce", "apex", "qa engineer", "quality assurance", "test engineer", "sdet",
        "software", "backend", "frontend", "full stack", "full-stack", "api", "developer",
        "python", "sql", "devops", "kubernetes",
    ]):
        return "Technical / Software"
    if any(x in t for x in ["product manager", "program manager", "project manager", "product owner"]):
        return "AI / LLM Product"
    if j.country == "Japan":
        return "Japan-focused"
    return "AI / LLM Product"


def evaluate(j):
    """Run the full rule-based pipeline on a Job in place: score, classify, recommend."""
    j.rule_score, j.strengths = score(j)
    classify(j)
    j.recommended_cv = cv(j)
    j.reason = "; ".join(j.strengths[:3] + j.gaps[:2]) or "No strong signals matched"
    j.recommendation = (
        "APPLY" if j.rule_score >= 75
        else "CONSIDER" if j.rule_score >= 50
        else "SKIP"
    )
    return j

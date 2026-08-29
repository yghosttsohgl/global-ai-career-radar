import yaml

with open("profile/master_profile.yaml", encoding="utf8") as f:
    PROFILE = yaml.safe_load(f)

# (label, keywords, points). Label is stored in Job.strengths when matched.
KEYWORD_GROUPS = [
    ("LLM / GenAI / NLP", ["llm", "genai", "machine learning", "nlp", "speech", "大模型", "大语言模型", "人工智能"], 25),
    ("Model evaluation / QA", ["evaluation", "model quality", "ai quality", "qa", "testing", "评测", "模型评估"], 20),
    ("Python / SQL / API", ["python", "sql", "api"], 10),
    ("Product / program management", ["product manager", "technical product", "program manager", "产品经理", "项目经理"], 10),
    ("English-friendly / international team", ["english", "international", "英文"], 10),
    ("Visa sponsorship mentioned", ["visa sponsorship", "visa support", "work visa", "签证", "工作许可"], 15),
    ("Speech (TTS/ASR)", ["tts", "asr", "voice", "语音", "语音识别", "语音合成"], 10),
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

    if any(k in t for k in ["native japanese", "business japanese", "fluent japanese", "jlpt n1", "商务日语", "日语n1"]):
        j.japanese_requirement = "BUSINESS_OR_HIGHER"
        gaps.append("Requires business-level+ Japanese; current speaking/writing is weak")
    elif any(k in t for k in ["japanese preferred", "conversational japanese", "日语优先", "日语加分"]):
        j.japanese_requirement = "PREFERRED_OR_CONVERSATIONAL"
    elif any(k in t for k in ["no japanese required", "english only", "english is the working language", "英文工作"]):
        j.japanese_requirement = "ENGLISH_FRIENDLY"

    j.gaps = gaps
    return j


def cv(j):
    t = f"{j.title} {j.description}".lower()
    if j.country == "China" or any(x in t for x in ["baidu", "百度", "大模型"]):
        return "AI / LLM Product" if any(x in t for x in ["product", "产品", "manager", "经理"]) else "China-focused"
    if any(x in t for x in ["evaluation", "nlp", "speech", "tts", "asr", "machine translation"]):
        return "AI / NLP / Evaluation"
    if any(x in t for x in ["software", "backend", "api", "developer", "python", "sql", "engineer"]):
        return "Technical / Software"
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

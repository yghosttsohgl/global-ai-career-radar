from .db import init, save
from .models import Job
from .scoring import score, classify, cv

init()

jobs = [
    Job(
        fingerprint="sample-jp",
        title="AI Evaluation Scientist",
        company="Example Japan AI",
        country="Japan",
        location="Tokyo",
        url="https://example.com/jp",
        source="sample",
        description="Evaluate LLMs with Python. English working environment. Visa support available."
    ),
    Job(
        fingerprint="sample-at",
        title="AI Product Manager",
        company="Example Austria AI",
        country="Austria",
        location="Vienna",
        url="https://example.com/at",
        source="sample",
        description="AI product role in an international English-speaking team."
    ),
    Job(
        fingerprint="sample-cn",
        title="大模型产品经理",
        company="Example China AI",
        country="China",
        location="Shanghai",
        url="https://example.com/cn",
        source="sample",
        description="负责大模型产品规划、模型评测和AI产品运营。"
    )
]

for job in jobs:
    job.rule_score = score(job)
    classify(job)
    job.recommended_cv = cv(job)
    job.recommendation = (
        "APPLY" if job.rule_score >= 75
        else "CONSIDER" if job.rule_score >= 50
        else "SKIP"
    )
    save(job)

print("Inserted sample jobs.")

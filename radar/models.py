from datetime import datetime, timezone
from pydantic import BaseModel, Field

class Job(BaseModel):
    fingerprint: str
    title: str
    company: str
    location: str = ""
    country: str = "Unknown"
    url: str = ""
    source: str = ""
    source_access: str = "public"
    description: str = ""
    language_requirement: str = "UNKNOWN"
    visa_status: str = "UNKNOWN"
    china_work_authorization: str = "UNKNOWN"
    first_seen: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_seen: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    rule_score: float = 0
    recommendation: str = ""
    recommended_cv: str = ""
    strengths: list[str] = []
    gaps: list[str] = []
    reason: str = ""

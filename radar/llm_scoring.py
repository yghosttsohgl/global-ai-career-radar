"""LLM-based scoring pass. Runs *after* the cheap rule-based scoring in
scoring.py, and only on jobs that already clear RULE_SCORE_FLOOR - this is
where an LLM read earns its cost: distinguishing real APPLY/CONSIDER
candidates and writing tailored reasoning, not re-triaging obvious SKIPs.
"""
import json
import os

import anthropic
import yaml

from .config import profile as _profile, scoring as _scoring
from .db import con, init

MODEL = os.environ.get("RADAR_LLM_MODEL") or _scoring()["llm"].get("model", "claude-opus-5")
RULE_SCORE_FLOOR = _scoring()["thresholds"]["llm_floor"]

RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "match_score": {"type": "integer", "minimum": 0, "maximum": 100},
        "verdict": {"type": "string", "enum": ["APPLY", "CONSIDER", "SKIP"]},
        "strengths": {"type": "array", "items": {"type": "string"}},
        "gaps": {"type": "array", "items": {"type": "string"}},
        "tailored_bullets": {"type": "array", "items": {"type": "string"}},
        "reasoning": {"type": "string"},
    },
    "required": ["match_score", "verdict", "strengths", "gaps", "tailored_bullets", "reasoning"],
    "additionalProperties": False,
}


def _profile_text():
    return yaml.safe_dump(_profile(), allow_unicode=True, sort_keys=False)


def _system_prompt():
    constraints = (_scoring()["llm"].get("hard_constraints") or "").strip()
    return (
        "You are a careful, honest job-matching assistant for one specific candidate. "
        "Given the candidate's profile and one job posting, evaluate fit for THAT candidate only.\n\n"
        f"{constraints}\n\n"
        "Be specific and honest in gaps; do not paper over missing requirements. tailored_bullets must be "
        "2-3 short CV bullet points drawn only from the candidate's real experience below, phrased to speak "
        "directly to this job's stated requirements - never invent experience the candidate doesn't have.\n\n"
        f"CANDIDATE PROFILE:\n{_profile_text()}"
    )


def pending_jobs(limit=None):
    """Jobs awaiting LLM scoring: at/above RULE_SCORE_FLOOR, or manually imported
    (the user chose to import those, so they always get a verdict)."""
    init()
    c = con()
    rows = c.execute(
        "SELECT * FROM jobs WHERE llm_score IS NULL "
        "AND (rule_score >= ? OR source = 'Manual import') ORDER BY rule_score DESC",
        (RULE_SCORE_FLOOR,),
    ).fetchall()
    c.close()
    return rows[:limit] if limit else rows


def apply_llm_result(fingerprint, result):
    """Write one evaluation (same shape as RESULT_SCHEMA) to the DB. Used by
    both the API-calling path below and manual scoring (e.g. done directly
    by Claude Code in a chat session against a Claude Pro/Max plan, with no
    separate API key or spend - see `pending`/`apply-llm-scores` in cli.py)."""
    c = con()
    c.execute(
        """UPDATE jobs SET
               llm_score = ?, llm_verdict = ?, llm_reasoning = ?, llm_tailored_bullets = ?,
               strengths = ?, gaps = ?
           WHERE fingerprint = ?""",
        (
            result["match_score"], result["verdict"], result["reasoning"],
            "|".join(result["tailored_bullets"]),
            "|".join(result["strengths"]), "|".join(result["gaps"]),
            fingerprint,
        ),
    )
    c.commit()
    c.close()


def evaluate_with_llm(job_row, client, system_prompt):
    user_content = (
        f"JOB POSTING\nTitle: {job_row['title']}\nCompany: {job_row['company']}\n"
        f"Country: {job_row['country']}  Location: {job_row['location'] or 'Unknown'}\n\n"
        f"{(job_row['description'] or '')[:6000]}"
    )
    response = client.messages.create(
        model=MODEL,
        max_tokens=2000,
        system=[{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}],
        output_config={"format": {"type": "json_schema", "schema": RESULT_SCHEMA}},
        messages=[{"role": "user", "content": user_content}],
    )
    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text)


def score_new_jobs(limit=None):
    """LLM-score jobs at/above RULE_SCORE_FLOOR that haven't been LLM-scored yet.
    Returns the number of jobs scored. Safe to call with no API key configured
    (prints a warning and does nothing) so `run` still completes locally."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("WARN llm_scoring: ANTHROPIC_API_KEY not set, skipping LLM scoring")
        return 0

    rows = pending_jobs(limit)
    client = anthropic.Anthropic()
    system_prompt = _system_prompt()

    scored = 0
    for row in rows:
        try:
            result = evaluate_with_llm(row, client, system_prompt)
        except Exception as e:
            print("WARN llm_scoring", row["fingerprint"], e)
            continue
        apply_llm_result(row["fingerprint"], result)
        scored += 1

    return scored

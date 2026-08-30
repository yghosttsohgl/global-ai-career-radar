---
name: score-jobs
description: Manually LLM-score pending Job Radar jobs against the candidate profile, without an Anthropic API key - use when the user asks to score, evaluate, or review new/pending jobs in this repo.
---

# Score pending Job Radar jobs (no API key needed)

This project (`japan_austria_china_job_radar`) normally LLM-scores jobs via
`radar/llm_scoring.py` calling the Anthropic API. When there's no
`ANTHROPIC_API_KEY` configured, do the same evaluation yourself instead,
using the user's Claude Pro/Max session - no separate API spend.

## Steps

1. Optionally refresh listings first, if the user wants current postings
   before scoring: `source .venv/bin/activate && python -m radar.cli scan`

2. Get the jobs awaiting scoring:
   ```
   source .venv/bin/activate && python -m radar.cli pending
   ```
   This returns JSON: jobs with `rule_score >= 40` that don't have an
   `llm_score` yet (see `RULE_SCORE_FLOOR` in `radar/llm_scoring.py` if that
   threshold ever changes). If it returns an empty list, say so and stop -
   there's nothing to score.

3. Read `radar/llm_scoring.py`'s `_system_prompt()` / `RESULT_SCHEMA` for the
   current rubric and required output shape, and `profile/master_profile.yaml`
   for the candidate's actual background - don't rely on memory of either,
   they may have been edited since.

4. For each pending job, evaluate honestly against the profile following
   that rubric. Weigh hard constraints as the rubric describes (Japan
   business-Japanese gap, China work-authorization gap, Austria no visa gap).
   `tailored_bullets` must be drawn only from real experience in the profile
   - never invent experience. Flag anything clearly wrong with a posting
   itself (e.g. explicitly closed/expired) as a SKIP with that as the reason,
   rather than scoring it on content.

5. Write the results as a JSON array (one object per job, matching
   `RESULT_SCHEMA`'s fields plus the job's `fingerprint`) to a scratch file,
   then apply them:
   ```
   python -m radar.cli apply-llm-scores < /path/to/results.json
   ```

6. Report a short summary back to the user: counts by verdict, and call out
   the standout APPLY(s) and anything notable (closed postings, hard
   blockers found, etc.) - don't just say "done."

## Notes

- This never touches `ANTHROPIC_API_KEY` or spends API credit - it's pure
  reasoning done in this chat session.
- Safe to re-run any time; `pending` only returns unscored jobs, so already-
  scored jobs are left alone.
- This does not send the email digest - that's a separate step
  (`python -m radar.cli digest`, needs Gmail secrets) and happens
  automatically in the scheduled GitHub Actions run regardless.

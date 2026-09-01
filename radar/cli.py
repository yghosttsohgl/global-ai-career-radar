import argparse

from .config import sources as _sources
from .db import init, jobs
from .scanners import SCANNER_REGISTRY, get_scanner


def scan():
    """Fetch every enabled source in sources.yaml and rule-score the postings."""
    init()
    for s in _sources():
        if not s.get("enabled", True):
            print(s["name"], "skipped (disabled)")
            continue
        scanner = get_scanner(s["type"])
        if not scanner:
            print("WARN", s["name"], f"unknown source type '{s.get('type')}' "
                  f"(known: {', '.join(sorted(SCANNER_REGISTRY))})")
            continue
        try:
            count = scanner(s)
            print(s["name"], f"done ({count} jobs)")
        except Exception as e:
            print("WARN", s["name"], e)


def stats():
    init()
    data = jobs()
    by_country, by_rec = {}, {}
    for j in data:
        by_country[j["country"]] = by_country.get(j["country"], 0) + 1
        by_rec[j["recommendation"] or "UNSCORED"] = by_rec.get(j["recommendation"] or "UNSCORED", 0) + 1
    print("Tracked jobs:", len(data))
    print("By country:", by_country)
    print("By recommendation:", by_rec)


def llm_score():
    from .llm_scoring import score_new_jobs
    n = score_new_jobs()
    print(f"LLM-scored {n} job(s).")


def pending():
    """Dump jobs awaiting LLM scoring as JSON - for manual scoring (e.g. by
    Claude Code itself in a chat session) when no ANTHROPIC_API_KEY is set."""
    import json as _json
    from .llm_scoring import pending_jobs
    rows = [dict(r) for r in pending_jobs()]
    print(_json.dumps(rows, indent=2, ensure_ascii=False))


def apply_llm_scores():
    """Read a JSON array of {fingerprint, match_score, verdict, strengths,
    gaps, tailored_bullets, reasoning} from stdin and write them to the DB -
    the write side of manual scoring, matching pending_jobs()'s output."""
    import json as _json
    import sys as _sys
    from .llm_scoring import apply_llm_result
    results = _json.loads(_sys.stdin.read())
    for r in results:
        apply_llm_result(r["fingerprint"], r)
    print(f"Applied {len(results)} LLM score(s).")


def rescore():
    """Re-run the rule-based pipeline (radar/scoring.py) over every stored job.
    Use after changing scoring.py / profile/scoring.yaml so existing rows pick
    up the new logic without a full rescan. LLM verdicts/reasoning/bullets and
    strengths/gaps on already LLM-scored jobs are left untouched; only the
    rule-derived fields refresh."""
    from .db import con
    from .models import Job
    from .scoring import evaluate

    init()
    c = con()
    rows = c.execute("SELECT * FROM jobs").fetchall()
    for r in rows:
        j = Job(
            fingerprint=r["fingerprint"], title=r["title"] or "", company=r["company"] or "",
            location=r["location"] or "", country=r["country"] or "Unknown",
            url=r["url"] or "", source=r["source"] or "", description=r["description"] or "",
        )
        evaluate(j)
        if r["llm_score"] is None:
            c.execute(
                """UPDATE jobs SET rule_score=?, recommendation=?, recommended_cv=?,
                       strengths=?, gaps=?, reason=?, language_requirement=?, visa_status=?
                   WHERE fingerprint=?""",
                (j.rule_score, j.recommendation, j.recommended_cv, "|".join(j.strengths),
                 "|".join(j.gaps), j.reason, j.language_requirement, j.visa_status, j.fingerprint),
            )
        else:
            c.execute(
                """UPDATE jobs SET rule_score=?, recommended_cv=?,
                       language_requirement=?, visa_status=?
                   WHERE fingerprint=?""",
                (j.rule_score, j.recommended_cv, j.language_requirement, j.visa_status,
                 j.fingerprint),
            )
    c.commit()
    c.close()
    print(f"Rescored {len(rows)} job(s).")


def digest():
    from .digest import send_digest
    send_digest()


def view():
    """Open the job database in Datasette for ad-hoc exploration (facets,
    SQL, canned queries from datasette.json). Read-only; Ctrl-C to stop."""
    import subprocess
    subprocess.run(["datasette", "data/jobs.sqlite3", "-m", "datasette.json", "--open"])


def run():
    """Full pipeline: scan sources, LLM-score promising jobs, email a digest."""
    scan()
    llm_score()
    digest()


COMMANDS = {
    "scan": scan,
    "stats": stats,
    "llm-score": llm_score,
    "pending": pending,
    "apply-llm-scores": apply_llm_scores,
    "rescore": rescore,
    "digest": digest,
    "view": view,
    "run": run,
}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("command", choices=list(COMMANDS))
    COMMANDS[p.parse_args().command]()


if __name__ == "__main__":
    main()

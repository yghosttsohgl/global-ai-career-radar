"""Email digest for jobs that are new and worth a look, sent once per job."""
import os
import smtplib
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from .db import con, init


def _pending_jobs(c):
    return c.execute("""
        SELECT * FROM jobs
        WHERE notified_at IS NULL
          AND COALESCE(llm_verdict, recommendation) IN ('APPLY', 'CONSIDER')
        ORDER BY COALESCE(llm_score, rule_score) DESC
    """).fetchall()


def _render_text(rows):
    lines = [f"Job Radar - {len(rows)} new match(es)\n"]
    for j in rows:
        score = j["llm_score"] if j["llm_score"] is not None else j["rule_score"]
        verdict = j["llm_verdict"] or j["recommendation"]
        lines.append(
            f"[{verdict}] {round(score)}/100 - {j['title']} @ {j['company']} "
            f"({j['country']}, {j['location'] or 'location unknown'})"
        )
        if j["url"]:
            lines.append(f"  {j['url']}")
        if j["llm_reasoning"]:
            lines.append(f"  Why: {j['llm_reasoning']}")
        if j["gaps"]:
            lines.append(f"  Gaps: {j['gaps'].replace('|', '; ')}")
        if j["llm_tailored_bullets"]:
            lines.append("  Suggested CV bullets:")
            for bullet in j["llm_tailored_bullets"].split("|"):
                lines.append(f"    - {bullet}")
        lines.append("")
    return "\n".join(lines)


def send_digest():
    if "GMAIL_ADDRESS" not in os.environ or "GMAIL_APP_PASSWORD" not in os.environ:
        print("WARN digest: GMAIL_ADDRESS/GMAIL_APP_PASSWORD not set, skipping digest")
        return 0

    init()
    c = con()
    rows = _pending_jobs(c)
    if not rows:
        print("No new jobs to notify.")
        c.close()
        return 0

    gmail_address = os.environ["GMAIL_ADDRESS"]
    gmail_password = os.environ["GMAIL_APP_PASSWORD"]
    to_addr = os.environ.get("DIGEST_TO", gmail_address)

    msg = MIMEMultipart()
    msg["Subject"] = f"Job Radar: {len(rows)} new match(es)"
    msg["From"] = gmail_address
    msg["To"] = to_addr
    msg.attach(MIMEText(_render_text(rows), "plain"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(gmail_address, gmail_password)
        smtp.send_message(msg)

    now = datetime.now(timezone.utc).isoformat()
    c.executemany(
        "UPDATE jobs SET notified_at = ? WHERE fingerprint = ?",
        [(now, r["fingerprint"]) for r in rows],
    )
    c.commit()
    c.close()
    print(f"Sent digest with {len(rows)} job(s).")
    return len(rows)

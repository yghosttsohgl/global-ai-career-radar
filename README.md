# Global AI Career Radar

A personal job radar for one candidate. It scans a fixed set of job boards for
tech + operations roles in **Japan**, **Austria** (also the EU / work-permit
bucket), and **Remote**, scores each posting against the candidate's profile —
first with cheap keyword rules, then optionally with an LLM — and surfaces the
good ones in a Streamlit dashboard and a daily email digest.

Everything specific to one job seeker is config, not code:

| File | Holds |
|---|---|
| [`profile/master_profile.yaml`](profile/master_profile.yaml) | the CV / background (source of truth; fed verbatim to the LLM) |
| [`profile/cv_versions.yaml`](profile/cv_versions.yaml) | the tailored CV variants |
| [`profile/scoring.yaml`](profile/scoring.yaml) | keyword groups + points, markets (visa + local-language rules), score thresholds, the seniority/experience/language penalties, CV-selection rules, and the LLM hard-constraint text |
| [`sources.yaml`](sources.yaml) | which job boards to scan (each `type:` picks a scanner in [`radar/scanners/`](radar/scanners/); `country:` must match a market in `scoring.yaml`) |

Swap those four and run `python -m radar.cli rescore` — no code changes needed.
[`radar/scoring.py`](radar/scoring.py) is a generic engine; [`radar/config.py`](radar/config.py) loads the config.

**Adding a job board on a new platform** (Lever, Workday, a country job API…):
drop a `radar/scanners/<name>.py` with a `@register("<type>")`-decorated
`scan(source) -> int` function (copy an existing one — they're ~25 lines), put
its base URL in `ENDPOINTS` in [`radar/scanners/__init__.py`](radar/scanners/__init__.py),
then add a `type: <type>` entry to `sources.yaml`. The package auto-discovers it.

---

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # then fill in whatever optional keys you have
```

Everything runs from the repo root. All commands below assume
`source .venv/bin/activate` first.

Secrets (all optional — each feature skips itself cleanly if its key is unset):

| Env var | Enables |
|---|---|
| `ANTHROPIC_API_KEY` | LLM scoring pass (`llm-score`). Without it, rule scores only. |
| `RADAR_LLM_MODEL` | Override the scoring model (default `claude-opus-5`). |
| `GMAIL_ADDRESS` / `GMAIL_APP_PASSWORD` / `DIGEST_TO` | Email digest. |
| `ADZUNA_APP_ID` / `ADZUNA_APP_KEY` | Adzuna Austria source. |
| `RAPIDAPI_KEY` | JSearch Japan source. |
| `CAREERJET_API_KEY` | Careerjet sources (disabled by default). |

---

## Commands

All are subcommands of `python -m radar.cli`:

| Command | What it does |
|---|---|
| `scan` | Fetch every enabled source in `sources.yaml`, rule-score each posting, upsert into `data/jobs.sqlite3`. |
| `llm-score` | LLM-score every job with `rule_score >= 40` that has no `llm_score` yet. **Needs `ANTHROPIC_API_KEY`** (no-ops with a warning otherwise). |
| `pending` | Dump the jobs awaiting LLM scoring as JSON (for manual scoring — see below). |
| `apply-llm-scores` | Read a JSON array of results from stdin and write them to the DB (the write side of manual scoring). |
| `rescore` | Re-run the rule pipeline over **every stored job**. Use after editing `radar/scoring.py`. LLM verdicts/reasoning on already-LLM-scored jobs are left untouched. |
| `stats` | Print counts by country and recommendation. |
| `digest` | Email the new APPLY/CONSIDER jobs once each. **Needs the Gmail vars.** |
| `view` | Open the job database in **Datasette** for ad-hoc exploration (see below). |
| `run` | Full pipeline: `scan` → `llm-score` → `digest`. This is what CI runs daily. |

### Dashboard

```bash
streamlit run dashboard/app.py
```

Opens at `localhost:8501` (titled **Career Radar**). A right-hand panel holds the
**market navigation** — one colour-coded button per market in `scoring.yaml`,
each showing how many jobs match that market's current filters — plus a
collapsible **Filters** panel; the selected market's jobs fill the main area.
`Remote` is shown as **Remote (global)** and `Vienna` as **Part-time (local)**
(the local part-time / stopgap service bucket); the `scoring.yaml` keys and DB
values are unchanged. Filters:

- **Minimum score** — hides jobs below this combined score.
- **Max years of experience required** (default 3) — hides roles asking for more
  years than the candidate has (`15` = no limit).
- **Hide senior / lead titles** (default on).
- **Hide native-language roles** (default on) — roles needing business/native
  German or Japanese.
- **Hide 'Not considered' roles** (default off) — drop `Not considered` jobs
  entirely instead of just greying them.
- **Application status** — show only jobs at a chosen pipeline stage (or `Unset`).

Each card shows the score, verdict badge, `🤖 AI-scored` / `📏 Rule-scored`, the
authorization + local-language read, strengths/gaps, the LLM's reasoning, and
(for AI-scored jobs) suggested CV bullets. Results are paged 10 at a time.

Each card has an **application-status** dropdown in its top-right corner —
`Interested`, `Applied`, `Interviewing`, `Offer`, `Rejected`, `Not considered` —
written straight to the `application_status` column in `data/jobs.sqlite3` (a
scan or the scheduled DB commit never touches it). It also drives the status
filter and Datasette's `pipeline` query. The status changes how the card looks:

- **Interested** — the card is highlighted (blue border + tint).
- **Not considered** — the card is greyed out (hover to see it normally).
- **Rejected** — the card is hidden everywhere, unless the status filter is set
  to `Rejected`.

### Datasette (ad-hoc exploration)

```bash
python -m radar.cli view
# or: datasette data/jobs.sqlite3 -m datasette.json --open
```

Opens at `localhost:8001`, read-only. Click any column to sort; use the facet
chips (`country`, `source`, `llm_verdict`, …) to filter; type SQL in the box.
Canned queries in [`datasette.json`](datasette.json): `ranked`, `to_score`,
`by_source`, `verdicts_by_country`, `pipeline`, `search_description`.

---

## How jobs are scored

Scoring runs in two passes. The **rule pass** runs on every job at scan time; the
**LLM pass** runs only on jobs that clear the rule floor. Wherever an LLM score
exists it overrides the rule score everywhere downstream
(`COALESCE(llm_score, rule_score)`).

All numbers, keyword lists, and market rules below are the defaults in
[`profile/scoring.yaml`](profile/scoring.yaml) — edit that file (then `rescore`)
rather than the code.

### Pass 1 — rule engine ([`radar/scoring.py`](radar/scoring.py) `evaluate()`)

**a. Keyword score — `score()`**
Lowercases `title + company + description` and checks it against 15 keyword
groups. Each group that matches adds its points **once**; points stack, capped at
100.

| Group | Pts | Group | Pts |
|---|--:|---|--:|
| QA / Testing / Test automation | 25 | Localization / i18n / linguistic | 20 |
| Salesforce / CRM / low-code | 25 | Software engineering | 18 |
| AI / GenAI / NLP / ML | 22 | Product / Program / Project management | 18 |
| AI model evaluation / quality | 15 | Data (analysis / quality / annotation) | 15 |
| Operations / Business operations | 15 | Visa sponsorship / relocation mentioned | 15 |
| Speech (TTS / ASR) | 12 | DevOps / Cloud | 12 |
| English-friendly / international team | 10 | Multilingual asset (JP / ZH / EN / DE) | 8 |
| Agile tooling / process | 6 | | |

Country bonus: **Austria +5** (no visa needed).

**b. Classify — `classify()`**
Sets `visa_status` and `language_requirement` per the job's market (`markets:` in
`scoring.yaml`) and records concrete `gaps`:

- **Visa** — `not_needed` markets → `NOT_NEEDED_FOR_USER`; `confirm_if_mentioned`
  → `CONFIRMED` only if the text mentions visa sponsorship/support, else
  `UNKNOWN` + a gap; `verify` → always `UNKNOWN` + a gap.
- **Local language** — a market's cue lists are scanned and one of
  `BUSINESS_OR_HIGHER` / `PREFERRED_OR_CONVERSATIONAL` / `ENGLISH_FRIENDLY` /
  `UNKNOWN` is returned. A `BUSINESS_OR_HIGHER` hit (e.g. "fließend Deutsch",
  "sehr gute Deutschkenntnisse", "C1 Deutsch", "business Japanese", "JLPT N1")
  adds a gap. Japan, Austria **and Vienna** have a `language:` block (Vienna
  tolerates B1/B2, only near-native asks are a gap); only markets without one
  (Remote) → `NOT_A_BARRIER_FOR_USER`.

**c. Overreach penalty — `_overreach_penalty()`**
Subtracts from the score (floored at 0) and adds a matching gap note, for roles
beyond a candidate with `CANDIDATE_YEARS = 3` years:

| Trigger | Penalty |
|---|---|
| Text asks for **N years of experience**, N > 3 | `−(10 + 6·(N−3))`, capped at **−35** (4y → −16, 5y → −22, ≥8y → −35). A figure only counts when an experience word is within ~30 chars. |
| **Senior title** — `senior / snr / sr / principal / lead / head / director / vp / chief` in the title | **−15** ("staff" / "architect" deliberately excluded) |
| **Native / business local language** — `language_requirement == BUSINESS_OR_HIGHER`, or a "native / 母語 / Muttersprache" cue | **−20** |

**d. Recommendation**
`recommended_cv` is chosen from keywords by `cv()`. Then:

```
rule_score >= 75  → APPLY
rule_score >= 50  → CONSIDER
else              → SKIP
```

A market can override these — the **Vienna** market (local part-time service
jobs) uses `apply: 45 / consider: 30`, since a solid entry-level service role
tops out around 50 on the keyword engine.

Jobs with `rule_score >= 40` (`RULE_SCORE_FLOOR` in
[`radar/llm_scoring.py`](radar/llm_scoring.py)) advance to the LLM pass.

### Pass 2 — LLM ([`radar/llm_scoring.py`](radar/llm_scoring.py))

For each qualifying job, sends the **full candidate profile** plus the posting
(first 6000 chars) to `claude-opus-5` with a rubric that weighs the hard
constraints — Japan business-Japanese gap, Japan visa-only-if-stated, Austria
no-visa-gap-but-C1-German-is, seniority vs ~3 years. Returns JSON:
`match_score` (0–100), `verdict` (APPLY/CONSIDER/SKIP), `strengths`, `gaps`,
`tailored_bullets` (2–3 CV bullets drawn only from real experience), `reasoning`.
Written to the `llm_*` columns.

### Manual LLM scoring — no API key

When `ANTHROPIC_API_KEY` is unset, the same evaluation can be done by Claude Code
in a chat session against a Claude Pro/Max plan (no API spend) via the
`score-jobs` skill:

```bash
python -m radar.cli pending > /tmp/pending.json
# Claude reads the rubric + profile, scores each job, writes results.json
python -m radar.cli apply-llm-scores < /tmp/results.json
```

Ask Claude Code to "score the pending jobs" or run `/score-jobs`.

---

## Scheduled runs

[`.github/workflows/radar.yml`](.github/workflows/radar.yml) runs
`python -m radar.cli run` daily at **06:00 UTC** and commits the updated
`data/jobs.sqlite3` back to `main` (so `first_seen` / `notified_at` persist). Set
the optional secrets in **Settings → Secrets and variables → Actions**; each
source/step skips itself if its secret is missing. Repo **Settings → Actions →
Workflow permissions** must be "Read and write".

---

## Layout

```
radar/            scan + score + digest pipeline
  cli.py          subcommands (scan, llm-score, rescore, view, run, …)
  config.py       loads profile/scoring.yaml, master_profile.yaml, sources.yaml
  scoring.py      generic rule engine (reads config.py)
  llm_scoring.py  LLM pass + manual-scoring read/write helpers
  scanners/       one self-registering module per job-board platform + shared helpers/ENDPOINTS
  digest.py       email digest
  db.py           SQLite schema + upsert
  models.py       the Job pydantic model
dashboard/app.py  Streamlit dashboard (markets/labels come from scoring.yaml)
profile/
  master_profile.yaml  the CV / background (source of truth)
  cv_versions.yaml     tailored CV variants
  scoring.yaml         keyword groups, markets, thresholds, penalties, LLM constraints
sources.yaml      which job boards to scan
datasette.json    Datasette facets + canned queries
data/jobs.sqlite3 the job database (tracked; CI commits it back)
```

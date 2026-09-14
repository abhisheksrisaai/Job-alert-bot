# Job Alert Automation

Scheduled pipeline that finds new Bangalore job postings for AI/product engineering and SDET roles, deduplicates, ranks relevance with Groq (Llama 3.3 70B) against your resume, and sends a Telegram digest. Runs on GitHub Actions cron — no server required.

## How it works

```
[GitHub Actions cron, once daily ~8:30am IST]
        ↓
[fetch_jobs.py] → TinyFish (LinkedIn) + SerpAPI (Google Jobs), Bangalore only
        ↓
[dedupe.py] → compares against seen_jobs.json, keeps only new
        ↓
[rank_jobs.py] → Groq scores relevance vs resume (product co. + AI/SDET focus)
        ↓
[notify.py] → Telegram digest of top matches
        ↓
[update seen_jobs.json, commit back to repo]
```

## Target profile (configured for Abhishek)

- **Location**: Bangalore / Bengaluru only (strict)
- **Company type**: product-based tech companies preferred over IT services
- **Roles**: AI/ML intern, SWE intern, SDET/QA automation intern, full-stack intern
- **Strengths**: FastAPI, React, Groq/RAG, Playwright, CI/CD, Azure

## Setup

### 1. API keys

| Variable | Where to get it |
|----------|-----------------|
| `TINYFISH_API_KEY` | [agent.tinyfish.ai/api-keys](https://agent.tinyfish.ai/api-keys) |
| `SERPAPI_KEY` | [serpapi.com](https://serpapi.com) (free tier) |
| `GROQ_API_KEY` | [console.groq.com](https://console.groq.com) (free tier) |
| `TELEGRAM_BOT_TOKEN` | Message `@BotFather` → `/newbot` |
| `TELEGRAM_CHAT_ID` | Message your bot, then `getUpdates` on the Telegram API |

Copy `.env.example` to `.env` and fill in values. **Never commit `.env` or put real keys in `.env.example`.**

For GitHub Actions, add all secrets under **Repo Settings → Secrets → Actions**.

### 2. Configure search

Edit `config/search_config.json` for roles, `exclude_keywords`, and `min_relevance_score`.

### 3. Resume

`config/resume.txt` holds your plain-text resume for Groq ranking context.

### 4. Test

```bash
pip install -r requirements.txt
cp .env.example .env   # if not already created
python src/main.py
```

Trigger manually from **Actions → Job Alert Check → Run workflow** before relying on cron.

## Ranking eval (measured, N=9)

`evals/rank_eval/` — 9 real Bangalore listings (live Google Jobs queries, Sept 2026),
hand-labeled by one reviewer against the strict filters, ranked live via Groq
(gpt-oss-20b). Sample, labels, and results are committed next to the scripts.

| Metric | Measured |
|---|---|
| Precision (of flagged relevant) | 8/9 = 0.89 |
| Recall (of label-relevant found) | 8/8 = 1.00 |
| Emitted digest links resolving (HTTP 200) | 9/9 |
| Eval spend | 6 SerpAPI searches + 2 Groq batch calls |

The one false positive is structural, not a fluke: "AI Intern" at RippleHire is a
**marketing** role, but the ranker only sees title/company/location/link — the word
"Marketing" lives in the description, which the pipeline drops before ranking.
Scores don't discriminate either: all 9 flagged jobs scored exactly 9/10, so
`min_relevance_score: 8` keeps everything and the boolean flag does all the work.
Passing the description into the ranking prompt is the obvious follow-up; not done here.

Caveats, stated plainly: N=9 with 8 positives is thin — SerpAPI returned results
for only 1 of 4 role queries tried (the rest came back empty). Labels are one
reviewer's judgment against description text the ranker never sees. Re-run with
`fetch_sample.py` (quota-guarded: refuses with fewer than 10 searches remaining)
plus `run_eval.py`.

## Failure handling

| Failure | Behavior |
|---|---|
| SerpAPI 429 / 5xx / connection drop | 3 attempts, backoff 1s/2s/4s, honors `Retry-After`; then skip source, pipeline continues |
| SerpAPI quota/plan/key error | No retry (would burn quota); skip source with warning |
| Failed SerpAPI searches | Not counted against monthly quota (previously every attempt incremented, silently shrinking the 100-search budget) |
| Google Jobs result with no apply/related links | Falls back to `share_link` (Google's per-job deep link — previously ignored, digest linked a generic search page); never emits the internal `job_id` blob |
| Groq 429 / 5xx / disconnect | 3 attempts, backoff 2s/4s/8s, honors `Retry-After`; auth/bad-request errors raise immediately; failed batch skipped, rest continue |
| Telegram send fails | 1 retry on connection error / 5xx; 4xx fails immediately (bad token won't fix itself) |
| SerpAPI flakiness (observed Sept 2026) | Frequent read-timeouts; retry absorbed 6+ with zero quota charged |

Unit tests (`tests/`, 13, all HTTP mocked, isolated cwd): link selection including
blob-never-emitted, quota counting, every retry path, every no-retry path.

## Cost awareness (measured)

- **SerpAPI**: 100 free searches/month. The eval spent 6 (including timed-out attempts
  that cost nothing after the quota fix). Daily cron at ~4 searches/run is ~120/month —
  OVER the free tier; trim `serpapi_dorks_per_run` or run every other day.
- **Groq**: free tier; the eval used 2 batch calls for 9 jobs. Negligible.
- **Telegram**: free. **Marginal cost of the whole eval: $0.**

## Tuning

- Raise `min_relevance_score` in `search_config.json` if digests are noisy.
- Add company names to `exclude_keywords` for firms you want to skip.
- Drop TinyFish LinkedIn fetch if flaky; SerpAPI alone is simpler.

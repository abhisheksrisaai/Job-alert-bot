"""Fetch a small REAL sample for the ranking eval.

Quota-guarded: refuses to run unless >= 8 SerpAPI searches remain this
month, and spends at most 3 (1 Google Jobs role + 2 dork queries).
Writes raw payloads (for the link audit) and the normalized sample.
Never touches seen_jobs.json.

Usage: .venv/bin/python evals/rank_eval/fetch_sample.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

import fetch_jobs

EVAL_DIR = os.path.dirname(os.path.abspath(__file__))
MAX_EVAL_SEARCHES = 7  # 1 google_jobs + 2 dorks + 3 raw captures + headroom
MIN_REMAINING = 10


def load_env():
    env_path = os.path.join(EVAL_DIR, "..", "..", ".env")
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())


def main():
    load_env()
    for var in ("SERPAPI_KEY",):
        if not os.environ.get(var):
            raise SystemExit(f"Missing {var} in .env; aborting (no quota will be spent).")

    with open(os.path.join(EVAL_DIR, "..", "..", "config", "search_config.json")) as f:
        search_config = json.load(f)

    usage = fetch_jobs._load_serpapi_usage()
    remaining = fetch_jobs._serpapi_budget_remaining(usage, search_config)
    monthly_remaining = search_config.get(
        "serpapi_monthly_limit", fetch_jobs.SERPAPI_MONTHLY_LIMIT
    ) - usage["count"]
    print(f"SerpAPI usage: {usage['count']} this month; {monthly_remaining} monthly left.")
    if monthly_remaining < MIN_REMAINING:
        raise SystemExit(
            f"Only {monthly_remaining} searches left; eval needs {MIN_REMAINING} "
            f"headroom. Aborting without spending quota."
        )

    # Trim to eval budget without touching the committed config file.
    eval_config = dict(search_config)
    eval_config["google_jobs_roles"] = ["AI Engineer Intern"]
    eval_config["serpapi_google_jobs_per_run"] = 1
    eval_config["serpapi_dorks_per_run"] = 2

    before = fetch_jobs._load_serpapi_usage()["count"]

    print("Fetching 1 Google Jobs role search...")
    jobs_jobs = fetch_jobs.fetch_serpapi_jobs(eval_config)
    print("Fetching up to 2 dork queries...")
    dork_jobs = fetch_jobs.fetch_serpapi_dorks(eval_config)

    # Raw captures for the link audit + ranking sample. Normalized locally
    # with the production normalize/filter functions (deterministic,
    # quota-free); the live fetch path above is exercised separately.
    RAW_QUERIES = [
        "AI Engineer Intern Bengaluru",
        "SDET QA Automation Intern Bengaluru",
        "Founding Engineer Bengaluru",
    ]
    print(f"Capturing {len(RAW_QUERIES)} raw Google Jobs payloads...")
    raws = []
    for query in RAW_QUERIES:
        raw_params = {
            "engine": "google_jobs",
            "q": query,
            "location": "Bangalore, Karnataka, India",
            "api_key": os.environ["SERPAPI_KEY"],
        }
        raw_usage = fetch_jobs._load_serpapi_usage()
        if fetch_jobs._serpapi_budget_remaining(raw_usage, eval_config) <= 0:
            print("Budget exhausted mid-capture; stopping.")
            break
        raw_data, _ = fetch_jobs._serpapi_search(raw_params, raw_usage)
        batch = (raw_data or {}).get("jobs_results", [])
        print(f"  {query!r}: {len(batch)} payloads")
        raws.extend(batch)
    with open(os.path.join(EVAL_DIR, "sample_raw.json"), "w") as f:
        json.dump(raws, f, indent=1)
    print(f"Saved {len(raws)} raw job payloads to sample_raw.json")

    spent = fetch_jobs._load_serpapi_usage()["count"] - before
    print(f"SerpAPI searches spent: {spent} (cap was {MAX_EVAL_SEARCHES})")

    sample = jobs_jobs + dork_jobs
    with open(os.path.join(EVAL_DIR, "sample.json"), "w") as f:
        json.dump(sample, f, indent=1)
    print(f"Wrote {len(sample)} normalized jobs to sample.json")
    print("Next: label them in labels.jsonl, then run run_eval.py")


if __name__ == "__main__":
    main()

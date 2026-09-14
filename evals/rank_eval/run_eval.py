"""Ranking eval: labels vs live Groq ranking + link audit.

- Runs the REAL rank_jobs.rank_jobs on evals/rank_eval/sample.json (live Groq).
- Compares model relevant flags against labels.jsonl (single reviewer).
- Link audit on sample_raw.json: old vs new link selection + live HTTP check
  of every emitted link.
- Writes results.json and prints the markdown table.

Usage: .venv/bin/python evals/rank_eval/run_eval.py
"""
import json
import os
import sys

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

import fetch_jobs
from rank_jobs import rank_jobs

EVAL_DIR = os.path.dirname(os.path.abspath(__file__))


def load_env():
    env_path = os.path.join(EVAL_DIR, "..", "..", ".env")
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())


def old_get_job_link(job):
    """Pre-fix logic, for before/after measurement."""
    apply_options = job.get("apply_options", [])
    if apply_options and apply_options[0].get("link"):
        return apply_options[0]["link"]
    related = job.get("related_links", [])
    if related and related[0].get("link"):
        return related[0]["link"]
    query = f"{job.get('title', '')} {job.get('company_name', '')}".replace(" ", "+")
    return f"https://www.google.com/search?q={query}&ibp=htl;jobs"


def check_link(url, timeout=12):
    try:
        r = requests.get(
            url,
            timeout=timeout,
            allow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (job-alert-bot eval)"},
        )
        return r.status_code
    except requests.RequestException as exc:
        return f"ERR:{type(exc).__name__}"


def main():
    load_env()
    if not os.environ.get("GROQ_API_KEY"):
        raise SystemExit("Missing GROQ_API_KEY; aborting.")

    with open(os.path.join(EVAL_DIR, "sample.json")) as f:
        sample = json.load(f)
    labels = {}
    with open(os.path.join(EVAL_DIR, "labels.jsonl")) as f:
        for line in f:
            if line.strip():
                lab = json.loads(line)
                labels[lab["sample_index"]] = lab
    with open(os.path.join(EVAL_DIR, "..", "..", "config", "search_config.json")) as f:
        search_config = json.load(f)
    with open(os.path.join(EVAL_DIR, "..", "..", "config", "resume.txt")) as f:
        resume_text = f.read()
    raws = json.load(open(os.path.join(EVAL_DIR, "sample_raw.json")))

    assert len(labels) == len(sample), "labels/sample size mismatch"
    n_pos = sum(1 for lab in labels.values() if lab["relevant"])
    print(f"Eval set: N={len(sample)} ({n_pos} label-relevant, {len(sample) - n_pos} label-irrelevant)")

    ranked = rank_jobs([dict(j) for j in sample], resume_text, search_config)
    flagged = {(j["title"], j.get("company")) for j in ranked}
    tp = fp = 0
    rows = []
    for i, job in enumerate(sample):
        lab = labels[i]
        pred = (job["title"], job.get("company")) in flagged
        truth = lab["relevant"]
        tp += pred and truth
        fp += pred and not truth
        score = next((j.get("score") for j in ranked if (j["title"], j.get("company")) == (job["title"], job.get("company"))), None)
        rows.append({
            "title": job["title"][:60], "company": job.get("company"),
            "label": truth, "predicted": pred, "score": score,
            "link_ok": fetch_jobs._is_job_specific_link(job.get("link")),
        })
    fn = n_pos - tp
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / n_pos if n_pos else 0.0
    print(f"Model flagged {tp + fp}/{len(sample)} relevant.")
    print(f"Precision: {tp}/{tp + fp} = {precision:.2f} | Recall: {tp}/{n_pos} = {recall:.2f}")

    # --- link audit on raw payloads ---
    print("\nLink audit (old logic vs fixed, on live payloads):")
    audit = []
    for j in raws:
        old, new = old_get_job_link(j), fetch_jobs.get_job_link(j)
        audit.append({
            "title": (j.get("title") or "")[:50],
            "has_apply": bool(j.get("apply_options")),
            "has_share": bool(j.get("share_link")),
            "has_related": bool(j.get("related_links")),
            "old_specific": fetch_jobs._is_job_specific_link(old),
            "new_specific": fetch_jobs._is_job_specific_link(new),
            "changed": old != new,
        })
    n = len(audit)
    print(f"  payloads with share_link (ignored by old code): {sum(a['has_share'] for a in audit)}/{n}")
    print(f"  payloads with related_links: {sum(a['has_related'] for a in audit)}/{n}")
    print(f"  old logic job-specific: {sum(a['old_specific'] for a in audit)}/{n}")
    print(f"  new logic job-specific: {sum(a['new_specific'] for a in audit)}/{n}")

    # --- live HTTP check of emitted links ---
    print("\nLive link check (emitted digest links):")
    live_ok = 0
    for i, job in enumerate(sample):
        status = check_link(job["link"])
        ok = isinstance(status, int) and status < 400
        live_ok += ok
        print(f"  [{i}] {status} {job['link'][:90]}")
    print(f"  resolving: {live_ok}/{len(sample)}")

    results = {
        "n": len(sample), "n_label_relevant": n_pos,
        "model_flagged": tp + fp, "tp": tp, "fp": fp, "fn": fn,
        "precision": round(precision, 3), "recall": round(recall, 3),
        "rows": rows,
        "link_audit": {
            "n_raw": n,
            "share_present": sum(a["has_share"] for a in audit),
            "old_specific": sum(a["old_specific"] for a in audit),
            "new_specific": sum(a["new_specific"] for a in audit),
        },
        "live_links_resolving": f"{live_ok}/{len(sample)}",
    }
    with open(os.path.join(EVAL_DIR, "results.json"), "w") as f:
        json.dump(results, f, indent=1)
    print("\nWrote results.json")


if __name__ == "__main__":
    main()

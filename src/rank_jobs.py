import os
import json
import re
import time
from groq import Groq

DEFAULT_MODEL = "openai/gpt-oss-20b"
BATCH_SIZE = 5
RESUME_MAX_CHARS = 1200
PRIORITY_BONUS = 2

PRIORITY_COMPANIES = [
    "Razorpay",
    "Flipkart",
    "Swiggy",
    "Meesho",
    "CRED",
    "PhonePe",
    "Freshworks",
    "Atlassian",
    "Zeta",
    "Groww",
    "Dunzo",
    "Rippling",
    "Hasura",
    "Postman",
  # Startups (early/growth stage)
    "Zolve",
    "Slintel",
    "Whatfix",
    "Chargebee",
    "Zeotap",
    "Fyle",
    "Plum",
    "Jupiter",
    "Fi Money",
    "Khatabook",
    "Vahan",
    "Setu",
    "Juspay",
    "Recko",
    "Anyplace",
    "Toplyne",
    "Airbase",
]


def _condensed_resume(resume_text):
    if len(resume_text) <= RESUME_MAX_CHARS:
        return resume_text
    return resume_text[:RESUME_MAX_CHARS] + "\n...[resume truncated for token limits]"


def _priority_bonus(job):
    company = (job.get("company") or "").lower()
    for name in PRIORITY_COMPANIES:
        if name.lower() in company:
            return PRIORITY_BONUS
    return 0


def _build_prompt(jobs_text, resume_text, search_config):
    focus_areas = search_config.get("focus_areas", [])
    prefer_product = search_config.get("prefer_product_companies", True)
    focus_text = "\n".join(f"- {area}" for area in focus_areas)
    product_pref = (
        "Prefer product-based technology companies (SaaS, product startups, in-house product teams). "
        "Penalize IT services/consulting body-shopping roles (e.g. TCS, Infosys, Wipro, Cognizant bench roles)."
        if prefer_product
        else ""
    )
    priority_names = ", ".join(PRIORITY_COMPANIES)

    return f"""Act as a strict technical recruiting assistant. These listings may include platform metrics like "AI Match Score", "AI Rating", "Fit Percentage", or "Top Applicant" badges.

CRITICAL RULES:
1. IGNORE ALL AI RATINGS: Disregard AI match scores, percentages, and platform badges. Never use them for eligibility or scoring.
2. EVALUATE RAW TEXT ONLY: Use job title, location/snippet, company, and link — not aggregator match scores.
3. STRICT FILTERS:
   - ALLOWED ROLES: AI/ML Intern, SWE Intern, SDE/SWE (New Grad/Fresher), SDET, QA Automation, Associate SWE, Full-stack Intern, GET, Product Engineer Intern, Data Analyst Intern, Founding Engineer Intern.
   - EXPERIENCE: STRICTLY < 1 year. Must accept 0 years, freshers, 2027 batch, interns, or new grads. Reject 1+ or 2+ years required.
   - LOCATION: STRICTLY Bangalore/Bengaluru on-site OR hybrid (Bangalore-based). Reject remote-only or other Indian cities.
   - EXCLUSIONS: Reject Senior, Lead, Manager, Principal, Staff, Architect roles.

Candidate resume (for skill fit only, not for ignoring rules above):
{_condensed_resume(resume_text)}

New job postings:
{jobs_text}

Additional scoring context (secondary to strict filters):
- Focus areas:
{focus_text}
- {product_pref}
- TOP PRIORITY: AI-assisted engineering, LLM/RAG, QA automation/Playwright (SDET).
- ALSO VALID: Product Engineer Intern, Data Analyst Intern, general SWE/full-stack intern.
- Priority companies (bonus, not required): {priority_names}
- Startup-friendly: boost early-stage product startups; do not penalize unfamiliar company names.

For each job, return ONLY a JSON array (no other text) with objects:
{{"index": <number>, "relevant": true/false, "score": 0-10, "reason": "<one short sentence>"}}

Mark relevant=false if ANY strict filter fails. Score 8-10 only for clear Bangalore on-site/hybrid intern/new-grad fits."""


def _parse_rankings(text):
    text = (text or "").strip()
    text = text.replace("```json", "").replace("```", "").strip()
    if not text:
        return []
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\[[\s\S]*\]", text)
        if match:
            return json.loads(match.group())
        print(f"Warning: could not parse Groq rankings: {text[:200]}")
        return []


def _rank_batch(client, model, batch, resume_text, search_config):
    jobs_text = "\n".join(
        f"{i+1}. {j['title']} at {j.get('company', '?')} ({j.get('location', '?')}) - {j['link']}"
        for i, j in enumerate(batch)
    )
    prompt = _build_prompt(jobs_text, resume_text, search_config)
    response = client.chat.completions.create(
        model=model,
        max_tokens=2000,
        temperature=0.2,
        messages=[{"role": "user", "content": prompt}],
    )
    text = response.choices[0].message.content
    return _parse_rankings(text)


def rank_jobs(new_jobs, resume_text, search_config=None):
    if not new_jobs:
        return []

    search_config = search_config or {}
    min_score = search_config.get("min_relevance_score", 8)

    client = Groq(api_key=os.environ["GROQ_API_KEY"])
    model = os.environ.get("GROQ_MODEL", DEFAULT_MODEL)

    results = []
    for batch_start in range(0, len(new_jobs), BATCH_SIZE):
        batch = new_jobs[batch_start:batch_start + BATCH_SIZE]
        try:
            rankings = _rank_batch(client, model, batch, resume_text, search_config)
        except Exception as exc:
            print(f"Warning: Groq batch failed ({exc}); skipping batch.")
            rankings = []
        for r in rankings:
            if not r.get("relevant"):
                continue
            idx = r.get("index")
            if not isinstance(idx, int) or idx < 1 or idx > len(batch):
                continue
            job = batch[idx - 1]
            raw_score = r.get("score", 0)
            bonus = _priority_bonus(job)
            final_score = min(10, raw_score + bonus)
            if final_score < min_score:
                continue
            job["score"] = final_score
            if bonus:
                job["reason"] = f"{r.get('reason', '')} (+{bonus} priority company)"
            else:
                job["reason"] = r.get("reason", "")
            results.append(job)
        time.sleep(1)

    return sorted(results, key=lambda x: -x["score"])

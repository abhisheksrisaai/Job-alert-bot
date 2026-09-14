import os
import time
import requests


def _escape_html(text):
    return (
        (text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def send_telegram_digest(ranked_jobs):
    if not ranked_jobs:
        print("No ranked jobs to send; skipping Telegram.")
        return

    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    url = f"https://api.telegram.org/bot{token}/sendMessage"

    message = "🎯 <b>New Job Matches</b>\n\n"
    for job in ranked_jobs[:10]:
        link = job.get("link", "")
        message += (
            f"<b>{_escape_html(job['title'])}</b> @ {_escape_html(job.get('company', '?'))}\n"
            f"📍 {_escape_html(job.get('location', '?'))} | Score: {job['score']}/10\n"
            f"💬 {_escape_html(job.get('reason', ''))}\n"
        )
        if link:
            message += f"🔗 <a href=\"{link}\">Apply</a>\n\n"
        else:
            message += "🔗 (no link)\n\n"

    last_error = None
    for attempt in range(2):
        try:
            response = requests.post(
                url,
                data={
                    "chat_id": chat_id,
                    "text": message[:4000],
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
                timeout=15,
            )
        except requests.RequestException as exc:
            last_error = f"request failed: {exc}"
            if attempt == 0:
                print(f"Warning: Telegram {last_error}; retrying once.")
                time.sleep(2)
                continue
            break
        try:
            data = response.json()
        except ValueError:
            data = {}
        if response.ok and data.get("ok"):
            print(f"Telegram digest sent ({min(len(ranked_jobs), 10)} jobs).")
            return
        # 5xx may clear on retry; 4xx (bad token/chat id) never will.
        if response.status_code >= 500 and attempt == 0:
            last_error = f"HTTP {response.status_code}"
            print(f"Warning: Telegram {last_error}; retrying once.")
            time.sleep(2)
            continue
        last_error = f"send failed: {data or response.status_code}"
        break
    print(f"Warning: Telegram digest not sent ({last_error}).")

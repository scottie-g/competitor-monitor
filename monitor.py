#!/usr/bin/env python3
"""Daily competitor page change monitor — writes AI summaries to Google Sheets."""

import os
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import anthropic
import gspread
import requests
from dotenv import load_dotenv

load_dotenv()

CD_BASE_URL = os.getenv("CD_BASE_URL", "https://app.changedetection.io")
CD_API_KEY = os.environ["CD_API_KEY"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
SHEET_ID = os.environ["SHEET_ID"]
LOOKBACK_HOURS = int(os.getenv("LOOKBACK_HOURS", "25"))
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL")


def cd_get(path: str):
    r = requests.get(
        f"{CD_BASE_URL}{path}",
        headers={"x-api-key": CD_API_KEY},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def recent_changes() -> list[dict]:
    """Return watches that have changed within the lookback window."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)
    watches = cd_get("/api/v1/watch")
    changed = []
    for uuid, info in watches.items():
        last_changed = info.get("last_changed")
        if last_changed and datetime.fromtimestamp(last_changed, tz=timezone.utc) > cutoff:
            changed.append({
                "uuid": uuid,
                "title": info.get("title") or "",
                "url": info.get("url", ""),
                "timestamp": last_changed,
            })
    return changed


def fetch_snapshots(uuid: str) -> tuple[str | None, str | None]:
    """Return (before_text, after_text) for the two most recent snapshots."""
    history = cd_get(f"/api/v1/watch/{uuid}/history")
    if not history:
        return None, None
    timestamps = sorted(history.keys(), key=int)
    if len(timestamps) < 2:
        return None, None

    def get(ts):
        r = requests.get(
            f"{CD_BASE_URL}/api/v1/watch/{uuid}/history/{ts}",
            headers={"x-api-key": CD_API_KEY},
            timeout=30,
        )
        return r.text[:4000] if r.ok else None

    return get(timestamps[-2]), get(timestamps[-1])


def summarize(title: str, url: str, before: str | None, after: str | None) -> str:
    """Ask Claude to write a competitive-intelligence summary of the change."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=300,
        messages=[{
            "role": "user",
            "content": (
                "You are a competitive intelligence analyst. A competitor's page has changed.\n\n"
                f"Page: {title or url}\nURL: {url}\n\n"
                f"BEFORE:\n{before or '(no prior snapshot)'}\n\n"
                f"AFTER:\n{after or '(no content)'}\n\n"
                "Write 2–4 sentences: (1) what specifically changed, "
                "(2) what it likely signals competitively. "
                "Be precise and direct. No bullet points."
            ),
        }],
    )
    return msg.content[0].text.strip()


def append_row(date_str: str, competitor: str, url: str, summary: str, diff_link: str) -> None:
    gc = gspread.oauth()
    sh = gc.open_by_key(SHEET_ID)
    sh.get_worksheet(0).append_row([date_str, competitor, url, summary, diff_link])


def notify_slack(competitor: str, summary: str, diff_link: str) -> None:
    if not SLACK_WEBHOOK_URL:
        return
    requests.post(SLACK_WEBHOOK_URL, json={
        "text": f"*{competitor}* page changed\n{summary}\n<{diff_link}|View diff>"
    }, timeout=10)


def main() -> None:
    print(f"Checking for changes in the last {LOOKBACK_HOURS}h...")
    changes = recent_changes()

    if not changes:
        print("No changes detected.")
        return

    print(f"{len(changes)} change(s) found.")

    for ch in changes:
        uuid, title, url = ch["uuid"], ch["title"], ch["url"]
        ts_dt = datetime.fromtimestamp(ch["timestamp"], tz=timezone.utc)
        date_str = ts_dt.strftime("%Y-%m-%d %H:%M UTC")
        competitor = title if title else urlparse(url).netloc.removeprefix("www.")
        diff_link = f"{CD_BASE_URL}/diff/{uuid}"

        print(f"  → {competitor}")
        before, after = fetch_snapshots(uuid)
        summary = summarize(title, url, before, after)
        append_row(date_str, competitor, url, summary, diff_link)
        notify_slack(competitor, summary, diff_link)
        print(f"    {summary[:100]}...")

    print("Done.")


if __name__ == "__main__":
    main()

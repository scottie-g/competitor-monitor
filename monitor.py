#!/usr/bin/env python3
"""Daily competitor page change monitor — writes AI summaries to Google Sheets."""

import hashlib
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import anthropic
import gspread
import requests
import yaml
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv(override=True)

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
SHEET_ID = os.environ["SHEET_ID"]
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL")

DB_PATH = Path(__file__).parent / "snapshots.db"
WATCHES_PATH = Path(__file__).parent / "watches.yaml"
SNAPSHOT_CHARS = 4000
RETENTION_DAYS = 30


# ── Database ──────────────────────────────────────────────────────────────────

def init_db() -> None:
    with sqlite3.connect(DB_PATH) as con:
        con.executescript("""
            CREATE TABLE IF NOT EXISTS snapshots (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                url        TEXT NOT NULL,
                fetched_at TEXT NOT NULL,
                content    TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_snapshots_url_fetched
                ON snapshots (url, fetched_at DESC);
        """)


def get_snapshots(url: str) -> tuple[str | None, str | None]:
    """Return (older, newer) text for the two most recent snapshots of a URL."""
    with sqlite3.connect(DB_PATH) as con:
        rows = con.execute(
            "SELECT content FROM snapshots WHERE url = ? ORDER BY fetched_at DESC LIMIT 2",
            (url,),
        ).fetchall()
    if len(rows) == 0:
        return None, None
    if len(rows) == 1:
        return None, rows[0][0]
    return rows[1][0], rows[0][0]   # older, newer


def save_snapshot(url: str, content: str) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with sqlite3.connect(DB_PATH) as con:
        con.execute(
            "INSERT INTO snapshots (url, fetched_at, content) VALUES (?, ?, ?)",
            (url, now, content),
        )
        con.execute(
            "DELETE FROM snapshots WHERE url = ? AND fetched_at < datetime('now', ?)",
            (url, f"-{RETENTION_DAYS} days"),
        )


# ── Watch list ────────────────────────────────────────────────────────────────

def load_watches() -> list[dict]:
    """Read watches.yaml and return the list of watch dicts."""
    with open(WATCHES_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("watches", [])


# ── Fetching ──────────────────────────────────────────────────────────────────

def fetch_page(url: str, js: bool) -> str | None:
    """
    Fetch a page and return clean plain text (max SNAPSHOT_CHARS).
    js=True uses Playwright (real browser); js=False uses requests + BeautifulSoup.
    Returns None on any error.
    """
    try:
        if js:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                text = page.inner_text("body")
                browser.close()
        else:
            r = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            text = soup.get_text(separator=" ", strip=True)
        return text[:SNAPSHOT_CHARS]
    except Exception as exc:
        print(f"    fetch error: {exc}")
        return None


# ── Summarization + output (unchanged) ───────────────────────────────────────

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
        "text": f"*{competitor}* page changed\n{summary}\n<{diff_link}|View page>"
    }, timeout=10)


# ── Main ──────────────────────────────────────────────────────────────────────

def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def main() -> None:
    init_db()
    watches = load_watches()
    print(f"Checking {len(watches)} watch(es)...")

    changed_count = 0
    for watch in watches:
        url = watch["url"]
        name = watch.get("name") or urlparse(url).netloc.removeprefix("www.")
        js = watch.get("js", False)

        print(f"  -> {name}")
        content = fetch_page(url, js)
        if content is None:
            print("    SKIP — fetch failed")
            continue

        before, _ = get_snapshots(url)
        old_hash = _sha256(before or "")
        new_hash = _sha256(content)

        save_snapshot(url, content)

        if old_hash == new_hash:
            print("    no change")
            continue

        changed_count += 1
        before, after = get_snapshots(url)   # re-fetch the saved pair
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        summary = summarize(name, url, before, after)
        append_row(date_str, name, url, summary, url)
        notify_slack(name, summary, url)
        print(f"    CHANGED: {summary[:100]}...")

    print(f"Done. {changed_count} change(s) reported.")


if __name__ == "__main__":
    main()

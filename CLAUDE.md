# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Setup

```powershell
pip install -r requirements.txt
playwright install chromium   # one-time: downloads the browser binary
cp .env.example .env          # then fill in values
```

## Running the script

```powershell
python monitor.py
```

To force a test without waiting for a real change (exercises Claude API + Sheets write):

```powershell
python -c "
from monitor import summarize, append_row
from datetime import datetime, timezone
before = 'Pro plan: \$49/month.'
after  = 'Pro plan: \$59/month.'
summary = summarize('Pricing', 'https://example.com/pricing', before, after)
append_row(datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC'), 'TEST', 'https://example.com/pricing', summary, '')
print(summary)
"
```

## Architecture

Single-file pipeline (`monitor.py`) with four stages that run sequentially for each watched URL:

1. **Load** — `load_watches()` reads `watches.yaml` to get the list of URLs to check.

2. **Fetch** — `fetch_page()` retrieves the page. Pages marked `js: true` use a headless Playwright/Chromium browser (for React/Vue sites); pages marked `js: false` use a plain HTTP request + BeautifulSoup. Output is capped at 4 000 chars of plain text.

3. **Compare** — The new page text is SHA-256 hashed and compared against the previous snapshot stored in `snapshots.db`. If the hashes match, the page is skipped. If they differ, the new snapshot is saved and processing continues.

4. **Summarize + Write** — `summarize()` sends the before/after pair to `claude-sonnet-4-6` with a competitive-intelligence prompt, returning a 2–4 sentence plain-English summary. `append_row()` writes a row to Google Sheets; `notify_slack()` posts an optional Slack notification.

## Watch list

URLs to monitor are defined in `watches.yaml` — edit this file to add or remove watches (no Python required):

```yaml
watches:
  - url: https://competitor.com/pricing
    name: Competitor Pricing     # shown in Sheets and Slack
    js: true                     # true = needs real browser (React/Vue)

  - url: https://another.com/features
    name: Another Features
    js: false                    # false = fast plain HTTP fetch
```

Page snapshots are stored in `snapshots.db` (SQLite, auto-created on first run, kept for 30 days). You can open it with [DB Browser for SQLite](https://sqlitebrowser.org/) to inspect history.

## Configuration

All secrets live in `.env`. Required variables raise `KeyError` on startup if missing; optional ones have defaults.

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | Yes | — | Anthropic API key for Claude summarization |
| `SHEET_ID` | Yes | — | Google Sheet ID from the URL |
| `SLACK_WEBHOOK_URL` | No | — | Slack Incoming Webhook URL; omit to disable notifications |

## Scheduling

Registered as Windows Task Scheduler task `CompetitorMonitor`, daily at 8 AM with `StartWhenAvailable` — runs on next boot if the machine was off. Manage via Task Scheduler GUI or:

```powershell
# Run immediately
Start-ScheduledTask -TaskName "CompetitorMonitor"

# Check last run result
Get-ScheduledTaskInfo -TaskName "CompetitorMonitor"
```

> **Playwright + Task Scheduler note:** `playwright install chromium` must be run under the same Windows user account that the scheduled task runs as. If the task can't find the browser, open Task Scheduler, check which user the task runs as, switch to that account, and re-run the install command.

## Google auth

`gspread.oauth()` opens a browser on first use to authorize. After that, the token at `%APPDATA%\gspread\authorized_user.json` is reused automatically. If auth breaks, delete that file and re-run the script manually to re-authorize.

# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

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

Single-file pipeline (`monitor.py`) with three stages that run sequentially:

1. **Fetch** — `recent_changes()` calls the changedetection.io REST API (`GET /api/v1/watch`) and filters watches whose `last_changed` timestamp falls within `LOOKBACK_HOURS` (default 25). For each hit, `fetch_snapshots()` retrieves the two most recent plaintext snapshots via `GET /api/v1/watch/{uuid}/history/{timestamp}`, capped at 4000 chars each.

2. **Summarize** — `summarize()` sends the before/after snapshot pair to `claude-sonnet-4-6` with a competitive-intelligence prompt. Returns a 2–4 sentence plain-English summary.

3. **Write** — `append_row()` authenticates via `gspread.oauth()` (token cached at `%APPDATA%\gspread\`) and appends one row to the Google Sheet.

## Configuration

All config lives in `.env`:

| Variable | Purpose |
|---|---|
| `CD_BASE_URL` | changedetection.io instance root (include the instance path for cloud) |
| `CD_API_KEY` | changedetection.io API key (Settings → API in the web UI) |
| `ANTHROPIC_API_KEY` | Anthropic API key for Claude summarization |
| `SHEET_ID` | Google Sheet ID from the URL |
| `LOOKBACK_HOURS` | How far back to look for changes (default 25 to survive missed 8 AM runs) |

## Scheduling

Registered as Windows Task Scheduler task `CompetitorMonitor`, daily at 8 AM with `StartWhenAvailable` — runs on next boot if the machine was off. Manage via Task Scheduler GUI or:

```powershell
# Run immediately
Start-ScheduledTask -TaskName "CompetitorMonitor"

# Check last run result
Get-ScheduledTaskInfo -TaskName "CompetitorMonitor"
```

## Google auth

`gspread.oauth()` opens a browser on first use to authorize. After that, the token at `%APPDATA%\gspread\authorized_user.json` is reused automatically. If auth breaks, delete that file and re-run the script manually to re-authorize.

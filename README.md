# competitor-monitor

Daily competitive intelligence pipeline. Detects changes on competitor pages via [changedetection.io](https://changedetection.io), summarizes them with Claude (Anthropic), and appends a row to a Google Sheet.

## How it works

1. **Fetch** — polls the changedetection.io API for pages that changed within the last `LOOKBACK_HOURS` (default 25h), retrieves before/after plaintext snapshots
2. **Summarize** — sends each before/after pair to Claude, which returns a 2–4 sentence competitive-intelligence summary
3. **Write** — appends one row per change to a Google Sheet: date, competitor, URL, summary, diff link

## Prerequisites

- Python 3.11+
- A [changedetection.io](https://changedetection.io) account (cloud or self-hosted) with pages configured to watch
- An [Anthropic API key](https://console.anthropic.com)
- A Google account with a Sheet to write results to

## Setup

**1. Install dependencies**
```
pip install -r requirements.txt
```

**2. Configure environment**
```
cp .env.example .env
```
Edit `.env` and fill in your values. See `.env.example` for descriptions of each variable.

**3. Authorize Google Sheets**

On first run, `gspread` will open a browser to authorize access. Follow the [gspread OAuth setup guide](https://docs.gspread.org/en/latest/oauth2.html) to create credentials and place them in the right location.

Note: you'll also need to enable the **Google Sheets API** and **Google Drive API** in your Google Cloud project before auth will succeed.

After the first authorization, the token is cached automatically and no browser is needed again. If auth breaks, delete `authorized_user.json` from the gspread config folder and re-run.

**4. Set up your Google Sheet**

Create a sheet with these columns in row 1:
```
Date | Competitor | URL | Summary | Diff Link
```
Copy the Sheet ID from the URL (`/spreadsheets/d/<SHEET_ID>/edit`) into your `.env`.

## Running

```
python monitor.py
```

To force a test without waiting for a real change (exercises the Claude API and Sheets write):

```python
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

## Slack notifications (optional)

Set `SLACK_WEBHOOK_URL` in your `.env` to receive a Slack message for each change detected. Works on Slack's free tier.

To get a webhook URL:
1. Go to [api.slack.com/apps](https://api.slack.com/apps) → Create New App → From scratch
2. Under **Add features and functionality**, choose **Incoming Webhooks** → toggle on → **Add New Webhook to Workspace**
3. Pick a channel → copy the webhook URL → paste it into `.env`

Each notification includes the competitor name, the AI summary, and a link to the diff.

## Scheduling (Windows)

Register as a daily Task Scheduler task so it runs automatically at 8 AM:

```powershell
$action = New-ScheduledTaskAction -Execute "python" -Argument "C:\path\to\monitor.py" -WorkingDirectory "C:\path\to\competitor-monitor"
$trigger = New-ScheduledTaskTrigger -Daily -At 8am
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable
Register-ScheduledTask -TaskName "CompetitorMonitor" -Action $action -Trigger $trigger -Settings $settings
```

`StartWhenAvailable` means it will run on next boot if the machine was off at 8 AM.

To run or check it manually:
```powershell
Start-ScheduledTask -TaskName "CompetitorMonitor"
Get-ScheduledTaskInfo -TaskName "CompetitorMonitor"
```

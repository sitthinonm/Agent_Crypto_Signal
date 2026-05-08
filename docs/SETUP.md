# Setup Guide (MVP)

## 1) Run Analyzer API

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
uvicorn analyzer_service.main:app --host 0.0.0.0 --port 8080 --reload
```

Test:

```bash
curl -X POST http://127.0.0.1:8080/analyze -H "Content-Type: application/json" -d "{\"symbols\":[\"BTCUSDT\",\"ETHUSDT\"],\"interval\":\"15m\",\"limit\":300}"
```

## 2) Configure Google Apps Script

1. Create new Apps Script project
2. Paste `gas/orchestrator.gs`
3. Set Script Properties:
   - `LINE_CHANNEL_ACCESS_TOKEN`
   - `LINE_TO`
   - `ANALYZER_URL` (example: `https://<host>/analyze`)
   - `SYMBOLS` (CSV, example: `BTCUSDT,ETHUSDT,SOLUSDT`)
   - `INTERVAL` (default `15m`)
   - `LIMIT` (default `300`)
   - `COOLDOWN_MINUTES` (default `10`)
   - `ERROR_COOLDOWN_MINUTES` (default `15`)
   - `DUPLICATE_CONFIDENCE_DELTA` (default `4`)
   - `AUDIT_SHEET_ID` (optional)
   - `AUDIT_SHEET_NAME` (optional, default `audit_log`)
   - `LINE_ADMIN_USER_IDS` (optional CSV for command authorization)
4. Create Trigger for `runAgentSignalCycle` every 15 minutes (or your own cycle)
5. (Optional) Enable LINE webhook command control
   - Deploy GAS as Web App (execute as you, access: anyone)
   - Set LINE Messaging API webhook URL to your Web App URL
   - Available commands in LINE:
     - `status`
     - `interval 5m`
     - `interval 15m`
     - `interval 30m`
     - `interval 1h`

## 3) Output Behavior

- On success: sends LINE Flex report (multi-symbol) + text header
- On duplicate signal within cooldown: skip push (anti-spam)
- On signal state transition (`action/mode/tier` changed): sends immediately
- On failure: sends error message to LINE OA with error cooldown
- On LINE command `interval ...`: updates `INTERVAL` and recreates trigger
- Saves latest audit state in Script Properties (`LAST_AUDIT_LOG`)
- Saves cycle metrics in Script Properties (`LAST_CYCLE_METRICS`)
- Optional: append full audit rows to Google Sheet

## 4) Analyzer Signal Output (bot-ready)

Each symbol now includes advisory fields to prepare for execution phase:

- `signal_action`: `ENTRY | PAUSE | INVALIDATE`
- `entry_mode`: `EARLY | CONFIRMED`
- `strategy_mode`: `WITH_TREND | COUNTER_TREND`
- `signal_id`
- `invalidate_condition`
- `position_sizing_hint`
- `time_stop_hint`
- `rr_estimate`
- `risk_grade`
- MTF/LTF scores and tier (`NORMAL | STRONG`)

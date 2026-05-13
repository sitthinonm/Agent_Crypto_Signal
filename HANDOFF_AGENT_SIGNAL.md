# Handoff: Agent Signal (Binance Futures + LINE OA)

## 1) Current Goal

Make scheduled Binance Futures analysis run reliably and send to LINE OA, with bot-ready output and low-setup operations.

---

## 2) What Has Been Implemented

### Analyzer API (`analyzer_service/`)

- FastAPI endpoints:
  - `GET /health`
  - `POST /analyze`
- Signal logic upgraded from simple EMA cross to adaptive multi-layer model:
  - MTF weighted bias (`30m/1h/4h/1d`)
  - LTF confluence scoring
  - output action state: `ENTRY | PAUSE | INVALIDATE`
  - strategy mode: `WITH_TREND | COUNTER_TREND`
  - entry mode: `EARLY | CONFIRMED`
- Risk/advisory fields added:
  - `rr_estimate`
  - `risk_grade`
  - `take_profit_3` (optional for strong trend-follow cases)
  - `trail_activation_price`
  - `trailing_stop_rule`
  - `signal_id`, `invalidate_condition`
- Replay validator added:
  - `scripts/replay_validation.py`

### GAS Orchestrator (`gas/orchestrator.gs`)

- Reads runtime config from Script Properties (no hardcoded symbols/interval required)
- Calls analyzer API every cycle
- Anti-spam logic:
  - cooldown
  - duplicate suppression
  - state transition send-through (`action/mode/tier` changes)
- Audit support:
  - `LAST_AUDIT_LOG`
  - `LAST_CYCLE_METRICS`
  - optional Google Sheet append
- LINE command webhook support (via `doPost`):
  - `status`
  - `interval 5m|15m|30m|1h`
- Robust LINE sending:
  - try Flex first
  - if Flex fails -> fallback text push
  - if text fails -> throw explicit error
  - logging added for response code/body

---

## 3) Cloud Deployment Status

### Render

- Service successfully deployed and live
- Health endpoint verified:
  - `https://agent-crypto-signal.onrender.com/health` -> OK
- Runtime pin used:
  - `runtime.txt` with `python-3.11.10`

### Known external limitation

- Binance Futures endpoint returned HTTP 451 from some host/IP routes.
- Mitigation applied by changing Render environment variable:
  - `BINANCE_FAPI_BASE_URL` to `https://fapi1.binance.com` (or fallback `fapi2/fapi3` if needed)

---

## 4) Main Problems Encountered

1. **No LINE message despite successful GAS run**
   - Root cause likely Flex payload rejection + muted HTTP exceptions.
   - Fixed with `pushLineWithFallback()` logic (Flex -> text fallback + explicit logs/errors).

2. **Analyzer 451 errors**
   - Not app syntax issue.
   - Caused by Binance legal/region restriction from host network path.

3. **Beginner UX friction**
   - User needed explicit step-by-step operation guidance.
   - Operational guidance should stay concise and click-by-click.

---

## 5) Files Changed (high impact)

- `analyzer_service/analysis.py`
- `analyzer_service/main.py`
- `analyzer_service/schemas.py`
- `gas/orchestrator.gs`
- `docs/SETUP.md`
- `README.md`
- `scripts/replay_validation.py`
- `runtime.txt`

---

## 6) Required Script Properties (GAS)

Minimum required:

- `LINE_CHANNEL_ACCESS_TOKEN`
- `LINE_TO`
- `ANALYZER_URL` = `https://agent-crypto-signal.onrender.com/analyze`

Core runtime config:

- `SYMBOLS` (CSV)
- `INTERVAL` (`5m|15m|30m|1h` preferred for ops command parity)
- `LIMIT`
- `COOLDOWN_MINUTES`
- `ERROR_COOLDOWN_MINUTES`
- `DUPLICATE_CONFIDENCE_DELTA`

Optional:

- `AUDIT_SHEET_ID`
- `AUDIT_SHEET_NAME`
- `LINE_ADMIN_USER_IDS`

---

## 7) Validation Checklist For Next Agent

1. **Analyzer reachability**
   - `GET /health` returns ok from browser and GAS request context.

2. **Analyzer data path**
   - test one `/analyze` request from GAS using `UrlFetchApp.fetch`.
   - if 451 recurs, rotate `BINANCE_FAPI_BASE_URL` (`fapi1` -> `fapi2` -> `fapi3`) or move region/host.

3. **LINE push baseline**
   - run direct push test function (`testLinePushNow`) and confirm code 200.

4. **Cycle delivery**
   - run `runAgentSignalCycle`
   - confirm at least text fallback arrives.

5. **Webhook command path**
   - ensure GAS web app deploy current version
   - verify LINE webhook
   - test `status` and `interval 15m`

6. **Observe state**
   - check `LAST_AUDIT_LOG` and `LAST_CYCLE_METRICS`

---

## 8) Recommended Next Work (Technical)

1. Add explicit debug function in GAS to print analyzer response code/body each cycle.
2. Add retry/backoff for analyzer call when exchange intermittently blocks one domain.
3. Add strict JSON size guards for Flex payload and auto-split by bubble count.
4. Add one-page beginner runbook (Thai) with screenshots and decision tree.
5. Add integration test script that validates:
   - Analyzer call success
   - LINE push success
   - Property completeness check

---

## 9) Quick Operational Commands

- Local compile check:
  - `python -m compileall analyzer_service`
- Replay check:
  - `python scripts/replay_validation.py`

### Windows VPS (minimal manual)

- One-shot installer script:
  - `scripts/deploy_windows_vps.ps1`
  - Run PowerShell **as Administrator**:
    - `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force`
    - `.\scripts\deploy_windows_vps.ps1`
  - Note: requires `winget` (Windows 10/11 App Installer). If missing, install App Installer / update Windows, then re-run.

---

## 10) Handoff Notes

- User expects very explicit beginner guidance (step-by-step, no assumptions).
- User is sensitive to repeated partial fixes; prefers single-pass durable solution.
- Prioritize deterministic diagnostics and visible errors over silent failure.

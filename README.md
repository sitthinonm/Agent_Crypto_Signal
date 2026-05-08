# Agent Signal (Binance Futures + LINE OA)

MVP system for scheduled crypto futures analysis:

- Pull market data from Binance Futures
- Generate MTF/LTF technical bias + entry plan + confidence (%)
- Send analysis results to LINE Official Account
- Designed to run on free/low-cost cloud stack with Google Apps Script scheduler

## Project Structure

- `analyzer_service/` - FastAPI analyzer API
- `gas/` - Google Apps Script orchestrator template
- `docs/` - architecture and setup docs
- `.env.example` - environment variable template

## Quick Start

1. Create virtual environment
2. Install dependencies
3. Copy `.env.example` to `.env`
4. Run analyzer API

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
uvicorn analyzer_service.main:app --host 0.0.0.0 --port 8080 --reload
```

## Endpoints

- `GET /health`
- `POST /analyze`

## Validation

- Replay validation (BTC/ETH/SOL, 15m):
  - `python scripts/replay_validation.py`

## Notes

- This repository is analysis/advisory first.
- Signal output is bot-ready (`ENTRY | PAUSE | INVALIDATE`, strategy mode, invalidation hints).
- GAS orchestrator supports LINE Flex, cooldown, duplicate suppression, and optional audit sheet.

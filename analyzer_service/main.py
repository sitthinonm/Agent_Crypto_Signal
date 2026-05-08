from fastapi import FastAPI, HTTPException

from .schemas import AnalyzeRequest, AnalyzeResponse, SymbolAnalysis, TradePlan
from .analysis import fetch_klines, derive_signal


app = FastAPI(title="Agent Signal Analyzer", version="0.1.0")


@app.get("/health")
async def health():
    return {"ok": True, "service": "agent-signal-analyzer"}


@app.post("/analyze", response_model=AnalyzeResponse)
async def analyze(req: AnalyzeRequest):
    analyses: list[SymbolAnalysis] = []
    for symbol in req.symbols:
        try:
            base_klines = await fetch_klines(symbol, req.interval, req.limit)
            htf_klines = {
                "30m": await fetch_klines(symbol, "30m", req.limit),
                "1h": await fetch_klines(symbol, "1h", req.limit),
                "4h": await fetch_klines(symbol, "4h", req.limit),
                "1d": await fetch_klines(symbol, "1d", min(req.limit, 180)),
            }
            result = derive_signal(symbol, req.interval, base_klines, htf_klines)
            analyses.append(
                SymbolAnalysis(
                    symbol=symbol.upper(),
                    trend_bias=result["trend_bias"],
                    market_regime=result["market_regime"],
                    last_price=result["last_price"],
                    support_zone=result["support_zone"],
                    resistance_zone=result["resistance_zone"],
                    plan=TradePlan(**result["plan"]),
                    news_context=None,
                )
            )
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Analyze failed for {symbol}: {exc}") from exc

    return AnalyzeResponse(interval=req.interval, analyses=analyses)

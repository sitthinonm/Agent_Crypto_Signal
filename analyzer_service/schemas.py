from pydantic import BaseModel, Field
from typing import List, Optional


class AnalyzeRequest(BaseModel):
    symbols: List[str] = Field(default_factory=lambda: ["BTCUSDT", "ETHUSDT"])
    interval: str = "15m"
    limit: int = 300
    include_news_context: bool = False


class TradePlan(BaseModel):
    direction: str
    entry_zone: str
    stop_loss: float
    take_profit_1: float
    take_profit_2: float
    take_profit_3: Optional[float] = None
    confidence_pct: int
    reasons: List[str]
    signal_action: str
    entry_mode: str
    strategy_mode: str
    signal_id: str
    invalidate_condition: str
    position_sizing_hint: str
    time_stop_hint: str
    mtf_long_score: int
    mtf_short_score: int
    ltf_long_score: int
    ltf_short_score: int
    dominant_bias: str
    htf_bias: str
    tier: str
    rr_estimate: float
    risk_grade: str
    trail_activation_price: Optional[float] = None
    trailing_stop_rule: Optional[str] = None


class SymbolAnalysis(BaseModel):
    symbol: str
    trend_bias: str
    market_regime: str
    last_price: float
    support_zone: str
    resistance_zone: str
    plan: TradePlan
    news_context: Optional[str] = None


class AnalyzeResponse(BaseModel):
    interval: str
    analyses: List[SymbolAnalysis]

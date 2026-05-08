from __future__ import annotations

from typing import Dict, List
import statistics
import httpx

from .config import settings

HTF_WEIGHTS = {"30m": 1, "1h": 2, "4h": 3, "1d": 4}
MTF_WEIGHT_SUM = sum(HTF_WEIGHTS.values())


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _ema(values: List[float], period: int) -> float:
    if not values:
        return 0.0
    if len(values) < period:
        return statistics.fmean(values)
    k = 2 / (period + 1)
    ema_value = statistics.fmean(values[:period])
    for price in values[period:]:
        ema_value = price * k + ema_value * (1 - k)
    return ema_value


def _atr(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> float:
    if not highs or not lows or not closes:
        return 0.0
    true_ranges: List[float] = []
    prev_close = closes[0]
    for high, low, close in zip(highs, lows, closes):
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        true_ranges.append(tr)
        prev_close = close
    if len(true_ranges) < period:
        return statistics.fmean(true_ranges)
    return statistics.fmean(true_ranges[-period:])


def _adx(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> float:
    if len(highs) < period + 2 or len(lows) < period + 2 or len(closes) < period + 2:
        return 0.0
    plus_dm: List[float] = []
    minus_dm: List[float] = []
    trs: List[float] = []
    for i in range(1, len(highs)):
        up_move = highs[i] - highs[i - 1]
        down_move = lows[i - 1] - lows[i]
        plus_dm.append(up_move if up_move > down_move and up_move > 0 else 0.0)
        minus_dm.append(down_move if down_move > up_move and down_move > 0 else 0.0)
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
        trs.append(tr)
    if len(trs) < period:
        return 0.0
    tr_n = sum(trs[-period:])
    if tr_n <= 0:
        return 0.0
    plus_di = 100.0 * (sum(plus_dm[-period:]) / tr_n)
    minus_di = 100.0 * (sum(minus_dm[-period:]) / tr_n)
    denom = plus_di + minus_di
    if denom <= 0:
        return 0.0
    return 100.0 * abs(plus_di - minus_di) / denom


def _vote_bias(closes: List[float], ema_fast: float, ema_slow: float) -> str:
    if ema_fast > ema_slow:
        return "LONG"
    if ema_fast < ema_slow:
        return "SHORT"
    return "LONG" if closes[-1] >= ema_slow else "SHORT"


async def fetch_klines(symbol: str, interval: str, limit: int) -> List[list]:
    url = f"{settings.binance_fapi_base_url}/fapi/v1/klines"
    params = {"symbol": symbol.upper(), "interval": interval, "limit": limit}
    async with httpx.AsyncClient(timeout=20.0) as client:
        res = await client.get(url, params=params)
        res.raise_for_status()
        return res.json()


def derive_signal(symbol: str, interval: str, base_klines: List[list], htf_klines: Dict[str, List[list]]) -> dict:
    if len(base_klines) < 60:
        last = base_klines[-1]
        last_price = float(last[4])
        signal_id = f"{symbol.upper()}:{interval}:PAUSE:{last[0]}"
        return {
            "trend_bias": "NEUTRAL",
            "market_regime": "RANGING",
            "last_price": last_price,
            "support_zone": f"{last_price * 0.995:.4f}-{last_price:.4f}",
            "resistance_zone": f"{last_price:.4f}-{last_price * 1.005:.4f}",
            "plan": {
                "direction": "NEUTRAL",
                "entry_zone": f"{last_price:.4f} - {last_price:.4f}",
                "stop_loss": round(last_price * 0.99, 6),
                "take_profit_1": round(last_price * 1.01, 6),
                "take_profit_2": round(last_price * 1.015, 6),
                "confidence_pct": 0,
                "reasons": ["Insufficient base timeframe candles (need >= 60)"],
                "signal_action": "PAUSE",
                "entry_mode": "EARLY",
                "strategy_mode": "WITH_TREND",
                "signal_id": signal_id,
                "invalidate_condition": "Wait for enough candles before directional signal",
                "position_sizing_hint": "0.0x",
                "time_stop_hint": "wait",
                "mtf_long_score": 0,
                "mtf_short_score": 0,
                "ltf_long_score": 0,
                "ltf_short_score": 0,
                "dominant_bias": "NEUTRAL",
                "htf_bias": "NEUTRAL",
                "tier": "NORMAL",
                "rr_estimate": 0.0,
                "risk_grade": "HIGH",
            },
        }

    closes = [float(k[4]) for k in base_klines]
    highs = [float(k[2]) for k in base_klines]
    lows = [float(k[3]) for k in base_klines]
    volumes = [float(k[5]) for k in base_klines]
    last_price = closes[-1]

    ema_fast = _ema(closes, 20)
    ema_slow = _ema(closes, 50)
    local_bias = _vote_bias(closes, ema_fast, ema_slow)

    mtf_long_score = 0
    mtf_short_score = 0
    for tf, weight in HTF_WEIGHTS.items():
        tf_klines = htf_klines.get(tf, [])
        if not tf_klines:
            continue
        tf_closes = [float(k[4]) for k in tf_klines]
        tf_fast = _ema(tf_closes, 20)
        tf_slow = _ema(tf_closes, 50)
        tf_vote = _vote_bias(tf_closes, tf_fast, tf_slow)
        if tf_vote == "LONG":
            mtf_long_score += weight
        else:
            mtf_short_score += weight

    if mtf_long_score > mtf_short_score:
        htf_bias = "LONG"
    elif mtf_short_score > mtf_long_score:
        htf_bias = "SHORT"
    else:
        htf_bias = "NEUTRAL"

    atr = _atr(highs, lows, closes, period=14)
    adx = _adx(highs, lows, closes, period=14)
    zone_ema = _ema(closes, 50)
    zone_width = max(atr * 0.6, last_price * 0.0025)
    discount_top = zone_ema - zone_width * 0.25
    discount_bottom = zone_ema - zone_width
    premium_bottom = zone_ema + zone_width * 0.25
    premium_top = zone_ema + zone_width

    in_discount = discount_bottom <= last_price <= discount_top
    in_premium = premium_bottom <= last_price <= premium_top
    touch_discount = bool(lows and lows[-1] <= discount_top)
    touch_premium = bool(highs and highs[-1] >= premium_bottom)
    deep_discount = last_price <= discount_bottom
    deep_premium = last_price >= premium_top

    trend_long = local_bias == "LONG"
    trend_short = local_bias == "SHORT"
    ema_retest_long = trend_long and lows[-1] <= ema_fast <= closes[-1]
    ema_retest_short = trend_short and highs[-1] >= ema_fast >= closes[-1]

    bullish_close = closes[-1] > closes[-2]
    bearish_close = closes[-1] < closes[-2]
    reversal_long_ready = (deep_discount or in_discount) and bullish_close
    reversal_short_ready = (deep_premium or in_premium) and bearish_close
    continuation_long_ready = trend_long and closes[-1] > ema_fast and closes[-2] > ema_fast
    continuation_short_ready = trend_short and closes[-1] < ema_fast and closes[-2] < ema_fast

    volume_baseline = statistics.fmean(volumes[-20:]) if len(volumes) >= 20 else statistics.fmean(volumes)
    atr_pct = (atr / last_price) if last_price > 0 else 0.0

    volume_mult = _clamp(0.92 + atr_pct / 0.025, 0.98, 1.22)
    volume_ok = volumes[-1] >= volume_baseline * volume_mult

    recent_range = (max(highs[-20:]) - min(lows[-20:])) if len(highs) >= 20 else (max(highs) - min(lows))
    range_mult = _clamp(3.8 - atr_pct / 0.035, 2.2, 4.8)
    range_ok = recent_range >= atr * range_mult if atr > 0 else True

    mtf_margin = abs(mtf_long_score - mtf_short_score)
    mtf_pressure = (
        (_clamp(mtf_margin / max(1, MTF_WEIGHT_SUM), 0.0, 1.0))
        if MTF_WEIGHT_SUM > 0
        else 0.0
    )

    vol_stress = _clamp((atr_pct - 0.005) / 0.035, 0.0, 1.8)
    adx_floor_base = _clamp(
        12.5 + vol_stress * 7.5 - mtf_pressure * 2.8,
        10.5,
        27.5,
    )
    trend_adx_bonus = _clamp(abs(ema_fast - ema_slow) / last_price / 0.004, 0.0, 1.6) if last_price > 0 else 0.0
    adx_threshold = _clamp(adx_floor_base + trend_adx_bonus * 4.8, adx_floor_base, 31.8)
    adx_ok = adx >= adx_threshold
    market_trend_ok = volume_ok and range_ok and adx_ok
    market_regime = "TRENDING" if market_trend_ok else "RANGING"
    if atr > 0 and (atr / last_price) >= 0.015:
        market_regime = "VOLATILE"

    long_score = 0
    short_score = 0
    long_score += 1 if trend_long else 0
    long_score += 2 if touch_discount else 0
    long_score += 1 if in_discount else 0
    long_score += 1 if ema_retest_long else 0
    long_score += 1 if reversal_long_ready else 0
    long_score += 1 if continuation_long_ready else 0
    long_score += 1 if htf_bias == "LONG" else 0
    long_score += 1 if volume_ok else 0
    long_score += 1 if range_ok else 0

    short_score += 1 if trend_short else 0
    short_score += 2 if touch_premium else 0
    short_score += 1 if in_premium else 0
    short_score += 1 if ema_retest_short else 0
    short_score += 1 if reversal_short_ready else 0
    short_score += 1 if continuation_short_ready else 0
    short_score += 1 if htf_bias == "SHORT" else 0
    short_score += 1 if volume_ok else 0
    short_score += 1 if range_ok else 0

    dominant_bias = "LONG" if long_score > short_score else "SHORT" if short_score > long_score else "NEUTRAL"
    score_gap = abs(long_score - short_score)
    max_score = max(1, long_score, short_score)
    confidence_pct = int(max(0, min(99, round(100 * score_gap / max_score))))

    counter_score_gap_need = round(_clamp(2 + 1.1 * atr_pct / 0.012 + 1.05 * vol_stress, 2.0, 5.8))
    counter_conf_floor = int(_clamp(53 + atr_pct / 0.022 * 38 + vol_stress * 10, 50, 86))
    entry_neutral_conf = int(
        _clamp(47 + atr_pct / 0.026 * 32 + vol_stress * 9 + (1 - market_trend_ok) * 6, 40, 86)
    )
    entry_aligned_conf = int(_clamp(40 + atr_pct / 0.029 * 30 + vol_stress * 8 + (1 - market_trend_ok) * 5, 36, 84))
    entry_confirmed_floor = int(_clamp(61 + atr_pct / 0.038 * 30 + vol_stress * 7, 53, 90))
    strong_tier_floor = int(_clamp(72 + mtf_pressure * 6 + (1 - market_trend_ok) * 4, 62, 91))

    counter_trend = htf_bias in ("LONG", "SHORT") and dominant_bias not in (htf_bias, "NEUTRAL")
    counter_trigger = (reversal_long_ready or reversal_short_ready) and (touch_discount or touch_premium)
    counter_trend_exception = (
        counter_trend
        and counter_trigger
        and score_gap >= counter_score_gap_need
        and confidence_pct >= counter_conf_floor
        and (
            (dominant_bias == "LONG" and reversal_long_ready)
            or (dominant_bias == "SHORT" and reversal_short_ready)
        )
    )

    signal_action = "PAUSE"
    entry_mode = "EARLY"
    strategy_mode = "WITH_TREND"
    if dominant_bias == "NEUTRAL":
        signal_action = "PAUSE"
    else:
        if htf_bias == "NEUTRAL":
            signal_action = "ENTRY" if confidence_pct >= entry_neutral_conf else "PAUSE"
            entry_mode = "EARLY" if confidence_pct < entry_confirmed_floor else "CONFIRMED"
        elif dominant_bias == htf_bias:
            signal_action = "ENTRY" if confidence_pct >= entry_aligned_conf else "PAUSE"
            entry_mode = "CONFIRMED" if confidence_pct >= entry_confirmed_floor else "EARLY"
        elif counter_trend_exception:
            signal_action = "ENTRY"
            strategy_mode = "COUNTER_TREND"
            entry_mode = "EARLY"
        else:
            signal_action = "INVALIDATE"

    support = min(lows[-30:]) if len(lows) >= 30 else min(lows)
    resistance = max(highs[-30:]) if len(highs) >= 30 else max(highs)
    rr_estimate = 0.0
    tp3 = None
    if dominant_bias == "NEUTRAL":
        entry_lo = min(last_price, zone_ema)
        entry_hi = max(last_price, zone_ema)
        stop_loss = last_price - atr if atr > 0 else last_price * 0.99
        tp1 = last_price + atr * 0.8 if atr > 0 else last_price * 1.01
        tp2 = last_price + atr * 1.2 if atr > 0 else last_price * 1.015
        signal_action = "PAUSE"
    elif dominant_bias == "LONG":
        entry_lo = max(support, last_price - atr * 0.55)
        entry_hi = min(last_price, zone_ema)
        stop_loss = min(support * 0.997, entry_lo - atr * 0.8)
        risk = max(entry_hi - stop_loss, atr * 0.6)
        tp1 = entry_hi + risk * 1.4
        tp2 = entry_hi + risk * 2.2
        tp3 = entry_hi + risk * 3.2
    else:
        entry_lo = max(last_price, zone_ema)
        entry_hi = min(resistance, last_price + atr * 0.55)
        stop_loss = max(resistance * 1.003, entry_hi + atr * 0.8)
        risk = max(stop_loss - entry_lo, atr * 0.6)
        tp1 = entry_lo - risk * 1.4
        tp2 = entry_lo - risk * 2.2
        tp3 = entry_lo - risk * 3.2

    if dominant_bias == "LONG":
        entry_mid = (entry_lo + entry_hi) * 0.5
        risk_abs = max(entry_mid - stop_loss, 1e-9)
        reward_abs = max(tp1 - entry_mid, 0.0)
        rr_estimate = reward_abs / risk_abs
    elif dominant_bias == "SHORT":
        entry_mid = (entry_lo + entry_hi) * 0.5
        risk_abs = max(stop_loss - entry_mid, 1e-9)
        reward_abs = max(entry_mid - tp1, 0.0)
        rr_estimate = reward_abs / risk_abs

    rr_floor = _clamp(1.15 + atr_pct * 12 + (0.2 if strategy_mode == "COUNTER_TREND" else 0.0), 1.2, 2.3)
    if signal_action == "ENTRY" and rr_estimate < rr_floor:
        signal_action = "PAUSE"
        bias_reasons_rr = f"RR gate paused signal: rr_estimate={rr_estimate:.2f} < rr_floor={rr_floor:.2f}"
    else:
        bias_reasons_rr = f"RR gate passed: rr_estimate={rr_estimate:.2f} rr_floor={rr_floor:.2f}"

    if counter_trend_exception:
        position_sizing_hint = "0.35x"
        time_stop_hint = "6 bars"
    elif (
        confidence_pct >= strong_tier_floor
        and market_trend_ok
        and htf_bias in (dominant_bias, "NEUTRAL")
    ):
        position_sizing_hint = "1.0x"
        time_stop_hint = "12 bars"
    elif confidence_pct >= entry_confirmed_floor - 12:
        position_sizing_hint = "0.6x"
        time_stop_hint = "10 bars"
    else:
        position_sizing_hint = "0.35x"
        time_stop_hint = "8 bars"

    bias_reasons = [
        f"HTF bias={htf_bias} (L{mtf_long_score}/S{mtf_short_score})",
        f"LTF score long={long_score} short={short_score}",
        f"Adaptive vol_pct={atr_pct * 100:.2f}% mtf_pressure={mtf_pressure:.2f}",
        (
            f"Adaptive gates volume_mult={volume_mult:.2f} range_mult={range_mult:.2f} "
            f"adx_thresh={adx_threshold:.1f} => volume_ok={volume_ok} "
            f"adx_ok={adx_ok} range_ok={range_ok}"
        ),
        (
            f"Adaptive ENTRY floors neutral={entry_neutral_conf} aligned={entry_aligned_conf} "
            f"confirmed_split={entry_confirmed_floor} strong_tier={strong_tier_floor} "
            f"counter_gap>={counter_score_gap_need} counter_conf>={counter_conf_floor}"
        ),
        bias_reasons_rr,
    ]

    signal_id = f"{symbol.upper()}:{interval}:{dominant_bias}:{base_klines[-1][0]}"
    if dominant_bias == "NEUTRAL":
        invalidate_condition = "No directional bias until LTF resolves the score tie"
    else:
        invalidate_condition = (
            f"Close {'below' if dominant_bias == 'LONG' else 'above'} "
            f"{stop_loss:.4f} or HTF rejects the setup continuation"
        )

    strong_follow_trend = (
        signal_action == "ENTRY"
        and strategy_mode == "WITH_TREND"
        and dominant_bias in ("LONG", "SHORT")
        and market_trend_ok
        and confidence_pct >= strong_tier_floor
        and rr_estimate >= rr_floor
    )
    if not strong_follow_trend:
        tp3 = None

    if signal_action != "ENTRY":
        risk_grade = "HIGH"
    elif strategy_mode == "COUNTER_TREND":
        risk_grade = "ELEVATED"
    elif confidence_pct >= strong_tier_floor and rr_estimate >= rr_floor + 0.25:
        risk_grade = "LOW"
    else:
        risk_grade = "MEDIUM"

    trail_activation_price = None
    trailing_stop_rule = None
    if signal_action == "ENTRY" and dominant_bias in ("LONG", "SHORT"):
        trail_buffer = max(atr * 0.85, last_price * 0.0035)
        trail_activation_price = tp1
        if dominant_bias == "LONG":
            trailing_stop_rule = (
                f"At TP1 ({tp1:.4f}) move SL->BE; then trail below swing low or -{trail_buffer:.4f}."
            )
        else:
            trailing_stop_rule = (
                f"At TP1 ({tp1:.4f}) move SL->BE; then trail above swing high or +{trail_buffer:.4f}."
            )

    plan = {
        "direction": dominant_bias,
        "entry_zone": f"{entry_lo:.4f} - {entry_hi:.4f}",
        "stop_loss": round(stop_loss, 6),
        "take_profit_1": round(tp1, 6),
        "take_profit_2": round(tp2, 6),
        "take_profit_3": round(tp3, 6) if tp3 is not None else None,
        "confidence_pct": confidence_pct,
        "reasons": bias_reasons,
        "signal_action": signal_action,
        "entry_mode": entry_mode,
        "strategy_mode": strategy_mode,
        "signal_id": signal_id,
        "invalidate_condition": invalidate_condition,
        "position_sizing_hint": position_sizing_hint,
        "time_stop_hint": time_stop_hint,
        "mtf_long_score": mtf_long_score,
        "mtf_short_score": mtf_short_score,
        "ltf_long_score": long_score,
        "ltf_short_score": short_score,
        "dominant_bias": dominant_bias,
        "htf_bias": htf_bias,
        "tier": "STRONG" if confidence_pct >= strong_tier_floor else "NORMAL",
        "rr_estimate": round(rr_estimate, 3),
        "risk_grade": risk_grade,
        "trail_activation_price": round(trail_activation_price, 6) if trail_activation_price is not None else None,
        "trailing_stop_rule": trailing_stop_rule,
    }

    return {
        "trend_bias": dominant_bias,
        "market_regime": market_regime,
        "last_price": float(last_price),
        "support_zone": f"{support:.4f}-{(support + atr * 0.5):.4f}",
        "resistance_zone": f"{(resistance - atr * 0.5):.4f}-{resistance:.4f}",
        "plan": plan,
    }

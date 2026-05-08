from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Dict, List
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analyzer_service.analysis import fetch_klines, derive_signal


SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
BASE_INTERVAL = "15m"
BASE_LIMIT = 500
HTF_LIMIT = 320
WARMUP_BARS = 120


@dataclass
class Metric:
    samples: int = 0
    pause_count: int = 0
    invalid_count: int = 0
    flip_count: int = 0
    transition_count: int = 0
    sent_count: int = 0


def _build_time_filtered(klines: List[list], ts: int) -> List[list]:
    return [k for k in klines if int(k[0]) <= ts]


def _compute_symbol_metrics(results: List[dict]) -> Metric:
    metric = Metric(samples=len(results))
    if not results:
        return metric

    prev_bias = None
    prev_action = None
    prev_mode = None
    prev_tier = None

    for row in results:
        plan = row["plan"]
        bias = plan["dominant_bias"]
        action = plan["signal_action"]
        mode = plan["strategy_mode"]
        tier = plan["tier"]

        if action == "PAUSE":
            metric.pause_count += 1
        if action == "INVALIDATE":
            metric.invalid_count += 1
        if action == "ENTRY":
            metric.sent_count += 1

        if prev_bias in ("LONG", "SHORT") and bias in ("LONG", "SHORT") and bias != prev_bias:
            metric.flip_count += 1

        if prev_action is not None and (action != prev_action or mode != prev_mode or tier != prev_tier):
            metric.transition_count += 1

        prev_bias = bias
        prev_action = action
        prev_mode = mode
        prev_tier = tier

    return metric


async def replay_symbol(symbol: str) -> Dict[str, float]:
    base = await fetch_klines(symbol, BASE_INTERVAL, BASE_LIMIT)
    htf_data = {
        "30m": await fetch_klines(symbol, "30m", HTF_LIMIT),
        "1h": await fetch_klines(symbol, "1h", HTF_LIMIT),
        "4h": await fetch_klines(symbol, "4h", HTF_LIMIT),
        "1d": await fetch_klines(symbol, "1d", min(HTF_LIMIT, 250)),
    }
    if len(base) <= WARMUP_BARS:
        raise RuntimeError(f"{symbol}: not enough candles for replay")

    rows: List[dict] = []
    for i in range(WARMUP_BARS, len(base)):
        base_slice = base[: i + 1]
        ts = int(base_slice[-1][0])
        htf_slice = {tf: _build_time_filtered(kl, ts) for tf, kl in htf_data.items()}
        rows.append(derive_signal(symbol, BASE_INTERVAL, base_slice, htf_slice))

    m = _compute_symbol_metrics(rows)
    denom = max(1, m.samples)
    return {
        "symbol": symbol,
        "samples": m.samples,
        "flip_rate": m.flip_count / denom,
        "pause_rate": m.pause_count / denom,
        "invalidation_rate": m.invalid_count / denom,
        "transition_send_ratio": m.transition_count / denom,
        "entry_ratio": m.sent_count / denom,
    }


async def main() -> None:
    per_symbol = await asyncio.gather(*(replay_symbol(s) for s in SYMBOLS))
    print("Replay Validation (15m)")
    print("=" * 72)
    for row in per_symbol:
        print(
            f"{row['symbol']:8} samples={row['samples']:3d} "
            f"flip={row['flip_rate']*100:5.2f}% "
            f"pause={row['pause_rate']*100:5.2f}% "
            f"invalidate={row['invalidation_rate']*100:5.2f}% "
            f"transition={row['transition_send_ratio']*100:5.2f}% "
            f"entry={row['entry_ratio']*100:5.2f}%"
        )

    avg = {
        "flip_rate": sum(r["flip_rate"] for r in per_symbol) / len(per_symbol),
        "pause_rate": sum(r["pause_rate"] for r in per_symbol) / len(per_symbol),
        "invalidation_rate": sum(r["invalidation_rate"] for r in per_symbol) / len(per_symbol),
        "transition_send_ratio": sum(r["transition_send_ratio"] for r in per_symbol) / len(per_symbol),
        "entry_ratio": sum(r["entry_ratio"] for r in per_symbol) / len(per_symbol),
    }
    print("-" * 72)
    print(
        "AVG      "
        f"flip={avg['flip_rate']*100:5.2f}% "
        f"pause={avg['pause_rate']*100:5.2f}% "
        f"invalidate={avg['invalidation_rate']*100:5.2f}% "
        f"transition={avg['transition_send_ratio']*100:5.2f}% "
        f"entry={avg['entry_ratio']*100:5.2f}%"
    )


if __name__ == "__main__":
    asyncio.run(main())

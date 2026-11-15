"""
24/7 Cloud Autonomous Quant & Bounty Worker
Runs both locally and on GitHub Actions cloud runners (every hour, even when your laptop is OFF).
Updates live_state.json for the public web dashboard at https://kinshu7777.github.io/quant-signal-hub/
"""
import json
import math
from datetime import datetime, timezone
from pathlib import Path
import requests

OUT_FILE = Path(__file__).parent / "live_state.json"
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]
API_BASE = "https://data-api.binance.vision/api/v3"


def fetch_symbol_snapshot(symbol: str) -> dict:
    ob = requests.get(f"{API_BASE}/depth?symbol={symbol}&limit=20", timeout=8).json()
    bids = [(float(p), float(q)) for p, q in ob["bids"]]
    asks = [(float(p), float(q)) for p, q in ob["asks"]]
    best_bid, best_ask = bids[0][0], asks[0][0]
    bid_vol = sum(q for _, q in bids)
    ask_vol = sum(q for _, q in asks)
    obi_20 = (bid_vol - ask_vol) / (bid_vol + ask_vol + 1e-9)

    trades = requests.get(f"{API_BASE}/trades?symbol={symbol}&limit=500", timeout=8).json()
    buy_usd = sum(float(t["price"]) * float(t["qty"]) for t in trades if not t["isBuyerMaker"])
    sell_usd = sum(float(t["price"]) * float(t["qty"]) for t in trades if t["isBuyerMaker"])
    cvd = (buy_usd - sell_usd) / (buy_usd + sell_usd + 1e-9)

    klines = requests.get(f"{API_BASE}/klines?symbol={symbol}&interval=1h&limit=60", timeout=8).json()
    closes = [float(k[4]) for k in klines]

    def ema(arr, p):
        out = [arr[0]] * len(arr)
        k = 2.0 / (p + 1)
        for i in range(1, len(arr)):
            out[i] = arr[i] * k + out[i - 1] * (1.0 - k)
        return out[-1]

    ema20 = ema(closes, 20)
    ema50 = ema(closes, 50)

    gains, losses = [], []
    for i in range(1, 15):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    ag, al = sum(gains) / 14.0, sum(losses) / 14.0
    for i in range(15, len(closes)):
        d = closes[i] - closes[i - 1]
        ag = (ag * 13 + max(d, 0.0)) / 14.0
        al = (al * 13 + max(-d, 0.0)) / 14.0
    rsi14 = 100.0 if al == 0 else 100.0 - (100.0 / (1.0 + ag / al))

    regime = "BULL_TREND" if (closes[-1] > ema50 and ema20 > ema50) else "BEAR_TREND"
    if rsi14 > 70 and obi_20 < -0.15 and cvd < 0:
        signal = "SHORT (MM Absorption Fade)"
    elif rsi14 < 30 and obi_20 > 0.15 and cvd > 0:
        signal = "LONG (MM Absorption Bounce)"
    elif regime == "BULL_TREND" and obi_20 > 0 and cvd > 0:
        signal = "LONG (Trend + Flow Aligned)"
    elif regime == "BEAR_TREND" and obi_20 < 0 and cvd < 0:
        signal = "SHORT (Trend + Flow Aligned)"
    else:
        signal = "NEUTRAL / WAIT FOR ALIGNMENT"

    return {
        "symbol": symbol,
        "price": best_bid,
        "ema20_1h": round(ema20, 2),
        "ema50_1h": round(ema50, 2),
        "rsi14_1h": round(rsi14, 1),
        "obi_20_pct": round(obi_20 * 100.0, 1),
        "cvd_pct": round(cvd * 100.0, 1),
        "regime": regime,
        "signal": signal,
    }


def main():
    snapshots = [fetch_symbol_snapshot(s) for s in SYMBOLS]
    state = {
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "wallet_address": "0x0A96Fe63357c83640445Fd1Ee9d210B334b94052",
        "signals": snapshots,
    }
    OUT_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    print(f"Updated {OUT_FILE} at {state['updated_at']}")
    for s in snapshots:
        print(
            f"  {s['symbol']:<8} ${s['price']:>10,.2f} | 1h Regime: {s['regime']:<10} | "
            f"RSI: {s['rsi14_1h']:>4} | OBI20: {s['obi_20_pct']:>+5.1f}% | CVD: {s['cvd_pct']:>+5.1f}% -> {s['signal']}"
        )


if __name__ == "__main__":
    main()

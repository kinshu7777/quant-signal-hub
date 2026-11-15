"""
24/7 Cloud Autonomous Quant, Multi-Chain Wallet & Bounty Worker
Runs both locally and on GitHub Actions cloud runners (every hour, even when your laptop is OFF).
Checks:
1. Live Binance Orderbook Microstructure & 1h Regime Signals (BTC, ETH, SOL, BNB)
2. Multi-Chain Wallet Balances (ETH, Base, Arbitrum, Optimism, Polygon - Native + USDC/USDT)
3. Live GitHub Bounty PR Status (#211, #212, #213)
Updates live_state.json for the public web dashboard at https://kinshu7777.github.io/quant-signal-hub/
"""
import json
from datetime import datetime, timezone
from pathlib import Path
import requests

OUT_FILE = Path(__file__).parent / "live_state.json"
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]
API_BASE = "https://data-api.binance.vision/api/v3"

WALLET_ADDRESS = "0x0A96Fe63357c83640445Fd1Ee9d210B334b94052"
PADDED_ADDRESS = WALLET_ADDRESS.lower().replace("0x", "").rjust(64, "0")
BALANCE_OF_DATA = "0x70a08231" + PADDED_ADDRESS

NETWORKS = {
    "Ethereum": {
        "rpc": "https://ethereum-rpc.publicnode.com",
        "native_symbol": "ETH",
        "tokens": {
            "USDC": ("0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48", 6),
            "USDT": ("0xdAC17F958D2ee523a2206206994597C13D831ec7", 6),
        },
    },
    "Base": {
        "rpc": "https://mainnet.base.org",
        "native_symbol": "ETH",
        "tokens": {
            "USDC": ("0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913", 6),
        },
    },
    "Arbitrum": {
        "rpc": "https://arb1.arbitrum.io/rpc",
        "native_symbol": "ETH",
        "tokens": {
            "USDC": ("0xaf88d065e77c8cC2239327C5EDb3A432268e5831", 6),
            "USDT": ("0xFd086bC7CD5C481DCC9C85ebE478A1C0b69FCbb9", 6),
        },
    },
    "Optimism": {
        "rpc": "https://mainnet.optimism.io",
        "native_symbol": "ETH",
        "tokens": {
            "USDC": ("0x0b2C639c533813f4Aa9D7837CAf62653d097Ff85", 6),
            "USDT": ("0x94b008aA00579c1307B0EF2c499aD98a8ce58e58", 6),
        },
    },
    "Polygon": {
        "rpc": "https://polygon-rpc.com",
        "native_symbol": "POL",
        "tokens": {
            "USDC": ("0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359", 6),
            "USDT": ("0xc2132D05D31c914a87C6611C10748AEb04B58e8F", 6),
        },
    },
}

TRACKED_PRS = [
    ("golang-cafe/job-board", 211, "Issue #45 - Dockerize Go App"),
    ("golang-cafe/job-board", 212, "Issue #97 - $100 Twitter API v2 Scheduler"),
    ("golang-cafe/job-board", 213, "Issue #91 - $100 LinkedIn Share Jobs API"),
]


def query_erc20_balance(rpc_url: str, contract: str, decimals: int) -> float:
    try:
        r = requests.post(
            rpc_url,
            json={
                "jsonrpc": "2.0",
                "method": "eth_call",
                "params": [{"to": contract, "data": BALANCE_OF_DATA}, "latest"],
                "id": 2,
            },
            timeout=6,
        )
        hex_val = r.json().get("result", "0x0")
        if not hex_val or hex_val == "0x":
            return 0.0
        return int(hex_val, 16) / (10 ** decimals)
    except Exception:
        return 0.0


def check_wallet_and_bounties(eth_price: float) -> dict:
    total_usd = 0.0
    chains = {}
    for chain, cfg in NETWORKS.items():
        rpc = cfg["rpc"]
        sym = cfg["native_symbol"]
        try:
            r = requests.post(
                rpc,
                json={"jsonrpc": "2.0", "method": "eth_getBalance", "params": [WALLET_ADDRESS, "latest"], "id": 1},
                timeout=6,
            )
            hex_bal = r.json().get("result", "0x0")
            native_bal = int(hex_bal, 16) / 1e18
            px = eth_price if sym == "ETH" else 0.25
            native_usd = native_bal * px
            tokens = {}
            tok_usd = 0.0
            for t_sym, (contract, dec) in cfg["tokens"].items():
                tb = query_erc20_balance(rpc, contract, dec)
                tokens[t_sym] = round(tb, 4)
                tok_usd += tb
            c_usd = native_usd + tok_usd
            total_usd += c_usd
            chains[chain] = {
                "native": round(native_bal, 6),
                "symbol": sym,
                "tokens": tokens,
                "usd": round(c_usd, 2),
            }
        except Exception:
            chains[chain] = {"status": "rpc_timeout", "usd": 0.0}

    headers = {"Accept": "application/vnd.github+json", "User-Agent": "kinshu7777-cloud-monitor"}
    prs = []
    any_merged = False
    for repo, pr_num, label in TRACKED_PRS:
        try:
            r = requests.get(f"https://api.github.com/repos/{repo}/pulls/{pr_num}", headers=headers, timeout=8)
            d = r.json()
            merged = bool(d.get("merged"))
            if merged:
                any_merged = True
            prs.append({
                "pr": pr_num,
                "label": label,
                "state": "MERGED" if merged else d.get("state", "open").upper(),
                "comments": d.get("comments", 0) + d.get("review_comments", 0),
                "url": d.get("html_url"),
            })
        except Exception:
            prs.append({"pr": pr_num, "label": label, "state": "UNKNOWN"})

    return {
        "total_wallet_usd": round(total_usd, 2),
        "ready_for_user_trade_approval": total_usd >= 5.0,
        "trading_lock_state": "STANDBY_AWAITING_USER_COMMAND",
        "any_bounty_merged": any_merged,
        "chains": chains,
        "bounty_prs": prs,
    }


def fetch_symbol_snapshot(symbol: str) -> dict:
    ob = requests.get(f"{API_BASE}/depth?symbol={symbol}&limit=20", timeout=8).json()
    bids = [(float(p), float(q)) for p, q in ob["bids"]]
    asks = [(float(p), float(q)) for p, q in ob["asks"]]
    best_bid = bids[0][0]
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
    if rsi14 >= 68:
        signal = "SHORT (Overbought RSI Exhaustion Fade)"
    elif rsi14 <= 32:
        signal = "LONG (Oversold RSI Absorption Bounce)"
    elif regime == "BULL_TREND" and rsi14 < 65 and obi_20 > 0.10 and cvd > 0:
        signal = "LONG (Trend + Orderflow Aligned)"
    elif regime == "BEAR_TREND" and rsi14 > 35 and obi_20 < -0.10 and cvd < 0:
        signal = "SHORT (Trend + Orderflow Aligned)"
    else:
        signal = "CASH / WAIT FOR HIGH-CONVICTION SETUP"

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
    eth_px = next((s["price"] for s in snapshots if s["symbol"] == "ETHUSDT"), 1820.0)
    earnings_monitor = check_wallet_and_bounties(eth_px)
    state = {
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "wallet_address": WALLET_ADDRESS,
        "earnings_monitor": earnings_monitor,
        "signals": snapshots,
    }
    OUT_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    print(f"Updated {OUT_FILE} at {state['updated_at']} | Wallet Total: ${earnings_monitor['total_wallet_usd']:.2f} USD")
    for s in snapshots:
        print(
            f"  {s['symbol']:<8} ${s['price']:>10,.2f} | 1h Regime: {s['regime']:<10} | "
            f"RSI: {s['rsi14_1h']:>4} | OBI20: {s['obi_20_pct']:>+5.1f}% | CVD: {s['cvd_pct']:>+5.1f}% -> {s['signal']}"
        )


if __name__ == "__main__":
    main()

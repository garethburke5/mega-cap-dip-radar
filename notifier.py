
import os
import json
import urllib.parse
import urllib.request
from pathlib import Path
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import yfinance as yf

WATCHLIST = {
    "TSLA": {"name": "Tesla", "opportunity": -20, "extreme": -30},
    "NVDA": {"name": "Nvidia", "opportunity": -20, "extreme": -30},
    "META": {"name": "Meta", "opportunity": -20, "extreme": -30},
    "AMZN": {"name": "Amazon", "opportunity": -15, "extreme": -25},
    "GOOGL": {"name": "Alphabet", "opportunity": -15, "extreme": -25},
}

LOOKBACK = 90
REVERSAL_CONFIRM = 5.0
STATE_FILE = Path("alert_state.json")

def load_prices(ticker, days=500):
    end = datetime.now(timezone.utc).date() + timedelta(days=1)
    start = end - timedelta(days=days)
    df = yf.download(ticker, start=start, end=end, auto_adjust=True, progress=False)
    if df.empty:
        return pd.DataFrame()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df[[c for c in ["Close", "Volume"] if c in df.columns]].dropna()

def calc_rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = -delta.clip(upper=0).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))

def analyse(ticker, cfg):
    df = load_prices(ticker)
    if df.empty or len(df) < 60:
        return None

    close = df["Close"]
    current = float(close.iloc[-1])
    high = float(close.rolling(LOOKBACK, min_periods=20).max().iloc[-1])
    drawdown = (current / high - 1) * 100
    low = float(close.iloc[-LOOKBACK:].min())
    rebound = (current / low - 1) * 100
    rsi = float(calc_rsi(close).iloc[-1])

    if drawdown <= cfg["extreme"] and rebound >= REVERSAL_CONFIRM:
        status = "EXTREME + REVERSAL"
    elif drawdown <= cfg["opportunity"] and rebound >= REVERSAL_CONFIRM:
        status = "REVERSAL ALERT"
    elif drawdown <= cfg["opportunity"]:
        status = "OPPORTUNITY"
    else:
        status = "NORMAL"

    return {
        "ticker": ticker,
        "name": cfg["name"],
        "price": current,
        "high": high,
        "drawdown": drawdown,
        "low": low,
        "rebound": rebound,
        "rsi": rsi,
        "status": status,
    }

def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            return {}
    return {}

def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2))

def telegram_send(text):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        raise RuntimeError("Telegram secrets are missing.")

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": "true",
    }).encode()

    req = urllib.request.Request(url, data=data, method="POST")
    with urllib.request.urlopen(req, timeout=20) as resp:
        if resp.status >= 400:
            raise RuntimeError(f"Telegram returned HTTP {resp.status}")

def main():
    state = load_state()
    new_state = dict(state)

    for ticker, cfg in WATCHLIST.items():
        result = analyse(ticker, cfg)
        if not result:
            continue

        previous = state.get(ticker, {}).get("status", "NORMAL")
        current = result["status"]

        should_alert = current in {"OPPORTUNITY", "REVERSAL ALERT", "EXTREME + REVERSAL"} and current != previous

        if should_alert:
            message = (
                f"📉 {ticker} — {current}\n"
                f"Price: ${result['price']:,.2f}\n"
                f"Drawdown from {LOOKBACK}d high: {result['drawdown']:.1f}%\n"
                f"Rebound from correction low: {result['rebound']:.1f}%\n"
                f"RSI: {result['rsi']:.0f}\n\n"
                f"Review the reason for the fall before trading."
            )
            telegram_send(message)

        new_state[ticker] = {
            "status": current,
            "price": result["price"],
            "drawdown": result["drawdown"],
            "rebound": result["rebound"],
            "updated_utc": datetime.now(timezone.utc).isoformat(),
        }

    save_state(new_state)

if __name__ == "__main__":
    main()

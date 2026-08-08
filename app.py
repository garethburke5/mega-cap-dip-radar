
import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta, timezone

st.set_page_config(page_title="Mega-Cap Dip Radar", page_icon="📉", layout="wide")

WATCHLIST = {
    "TSLA": {"name": "Tesla", "opportunity": -20, "extreme": -30},
    "NVDA": {"name": "Nvidia", "opportunity": -20, "extreme": -30},
    "META": {"name": "Meta", "opportunity": -20, "extreme": -30},
    "AMZN": {"name": "Amazon", "opportunity": -15, "extreme": -25},
    "GOOGL": {"name": "Alphabet", "opportunity": -15, "extreme": -25},
}

DEFAULT_LOOKBACK = 90
DEFAULT_REVERSAL = 5.0

@st.cache_data(ttl=300)
def load_prices(ticker, days=500):
    end = datetime.now(timezone.utc).date() + timedelta(days=1)
    start = end - timedelta(days=days)
    df = yf.download(ticker, start=start, end=end, auto_adjust=True, progress=False)
    if df.empty:
        return pd.DataFrame()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    cols = [c for c in ["Close", "Volume"] if c in df.columns]
    return df[cols].dropna()

def calc_rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = -delta.clip(upper=0).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))

def score_stock(drawdown, rsi, dist50, vol_ratio, rebound, opportunity, extreme, reversal):
    score = 0
    if drawdown <= extreme:
        score += 55
    elif drawdown <= opportunity:
        score += 42
    elif drawdown <= opportunity * 0.75:
        score += 28
    elif drawdown <= opportunity * 0.5:
        score += 15

    if np.isfinite(rsi):
        if rsi < 25: score += 18
        elif rsi < 30: score += 15
        elif rsi < 35: score += 10
        elif rsi < 40: score += 5

    if np.isfinite(dist50):
        if dist50 < -15: score += 12
        elif dist50 < -10: score += 9
        elif dist50 < -5: score += 5

    if np.isfinite(vol_ratio):
        if vol_ratio >= 2: score += 8
        elif vol_ratio >= 1.5: score += 5
        elif vol_ratio >= 1.2: score += 3

    if drawdown <= opportunity:
        if rebound >= reversal: score += 12
        elif rebound >= max(2, reversal/2): score += 6

    return min(100, int(round(score)))

def get_status(drawdown, rebound, score, opportunity, extreme, reversal):
    if drawdown <= extreme and rebound >= reversal:
        return "EXTREME + REVERSAL"
    if score >= 80:
        return "HIGH PRIORITY"
    if drawdown <= opportunity and rebound >= reversal:
        return "REVERSAL ALERT"
    if drawdown <= opportunity:
        return "OPPORTUNITY"
    if score >= 45:
        return "WATCH"
    return "NORMAL"

def analyse(ticker, cfg, lookback, reversal):
    df = load_prices(ticker)
    if df.empty or len(df) < 60:
        return None, df

    close = df["Close"]
    current = float(close.iloc[-1])
    rolling_high = float(close.rolling(lookback, min_periods=20).max().iloc[-1])
    drawdown = (current / rolling_high - 1) * 100

    low = float(close.iloc[-lookback:].min())
    rebound = (current / low - 1) * 100

    rsi = float(calc_rsi(close).iloc[-1])
    ma50 = float(close.rolling(50).mean().iloc[-1])
    dist50 = (current / ma50 - 1) * 100

    vol20 = float(df["Volume"].rolling(20).mean().iloc[-1])
    vol_ratio = float(df["Volume"].iloc[-1] / vol20) if vol20 else np.nan

    score = score_stock(
        drawdown, rsi, dist50, vol_ratio, rebound,
        cfg["opportunity"], cfg["extreme"], reversal
    )
    status = get_status(
        drawdown, rebound, score,
        cfg["opportunity"], cfg["extreme"], reversal
    )

    return {
        "Ticker": ticker,
        "Company": cfg["name"],
        "Price": current,
        "Rolling High": rolling_high,
        "Drawdown %": drawdown,
        "Correction Low": low,
        "Rebound %": rebound,
        "RSI": rsi,
        "50DMA Distance %": dist50,
        "Volume Ratio": vol_ratio,
        "Score": score,
        "Status": status,
        "Opportunity Trigger": cfg["opportunity"],
        "Extreme Trigger": cfg["extreme"],
    }, df

st.title("Mega-Cap Dip Radar")
st.caption("Focused on large corrections and rebound opportunities in five mega-cap shares.")

with st.sidebar:
    st.header("Live settings")
    lookback = st.selectbox("Rolling high window", [60, 90, 126, 252], index=1)
    reversal = st.slider("Reversal confirmation %", 0, 10, 5, 1)
    st.caption("Scheduled Telegram alerts use the defaults in notifier.py.")

rows = []
series = {}
for ticker, cfg in WATCHLIST.items():
    row, df = analyse(ticker, cfg, lookback, reversal)
    if row:
        rows.append(row)
        series[ticker] = df

if not rows:
    st.error("Market data is unavailable right now.")
    st.stop()

summary = pd.DataFrame(rows).sort_values(["Score", "Drawdown %"], ascending=[False, True])

cards = st.columns(5)
for col, (_, row) in zip(cards, summary.sort_values("Ticker").iterrows()):
    with col:
        st.metric(
            f'{row["Ticker"]} · {row["Status"]}',
            f'${row["Price"]:,.2f}',
            f'{row["Drawdown %"]:.1f}% from high'
        )
        st.caption(f'Score {row["Score"]}/100 · RSI {row["RSI"]:.0f}')

st.subheader("Opportunity ranking")
show = summary[[
    "Ticker","Price","Drawdown %","Rebound %","RSI",
    "50DMA Distance %","Volume Ratio","Score","Status"
]].copy()

st.dataframe(
    show.style.format({
        "Price": "${:,.2f}",
        "Drawdown %": "{:.1f}%",
        "Rebound %": "{:.1f}%",
        "RSI": "{:.0f}",
        "50DMA Distance %": "{:.1f}%",
        "Volume Ratio": "{:.2f}×",
        "Score": "{:.0f}",
    }),
    use_container_width=True,
    hide_index=True
)

top = summary.iloc[0]
st.info(
    f'Highest-priority stock: {top["Ticker"]} · {top["Status"]} · '
    f'score {top["Score"]}/100 · drawdown {top["Drawdown %"]:.1f}%.'
)

st.subheader("Charts")
tabs = st.tabs(list(WATCHLIST.keys()))
for tab, ticker in zip(tabs, WATCHLIST.keys()):
    with tab:
        row = summary[summary["Ticker"] == ticker].iloc[0]
        df = series[ticker].copy()
        chart = pd.DataFrame(index=df.index)
        chart["Close"] = df["Close"]
        chart["50DMA"] = df["Close"].rolling(50).mean()
        chart[f"{lookback}d High"] = df["Close"].rolling(lookback, min_periods=20).max()
        st.line_chart(chart.tail(max(180, lookback*2)))

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Drawdown", f'{row["Drawdown %"]:.1f}%')
        c2.metric("Rebound", f'{row["Rebound %"]:.1f}%')
        c3.metric("RSI", f'{row["RSI"]:.0f}')
        c4.metric("Score", f'{row["Score"]}/100')

        if row["Drawdown %"] <= row["Opportunity Trigger"] and row["Rebound %"] < reversal:
            st.warning("Opportunity threshold reached, but rebound confirmation has not yet appeared.")
        elif row["Drawdown %"] <= row["Opportunity Trigger"] and row["Rebound %"] >= reversal:
            st.success("Opportunity threshold + rebound confirmation are both present. Review the setup.")

st.divider()
st.caption(
    "Decision-support only. A large drawdown is not an automatic buy signal. "
    "Review current fundamentals and the reason for the fall before trading."
)


import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
import plotly.graph_objects as go
from datetime import datetime, timedelta, timezone

st.set_page_config(page_title="Mega-Cap Dip Radar v3", page_icon="🎯", layout="wide")

WATCHLIST = ["TSLA","NVDA","META","AMZN","GOOGL"]
PERIODS = {"1D":1,"2D":2,"5D":5,"7D":7,"10D":10,"1M":21,"3M":63,"6M":126,"12M":252}

@st.cache_data(ttl=300)
def load(ticker, years=10):
    end = datetime.now(timezone.utc).date() + timedelta(days=1)
    start = end - timedelta(days=int(years*365.25)+30)
    df = yf.download(ticker, start=start, end=end, auto_adjust=True, progress=False)
    if df.empty:
        return df
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    cols=[c for c in ["Open","High","Low","Close","Volume"] if c in df.columns]
    return df[cols].dropna()

def rsi(s,n=14):
    d=s.diff()
    g=d.clip(lower=0).rolling(n).mean()
    l=-d.clip(upper=0).rolling(n).mean()
    rs=g/l.replace(0,np.nan)
    return 100-(100/(1+rs))

def period_table(df):
    c=df["Close"]
    current=float(c.iloc[-1])
    rows=[]
    for label,d in PERIODS.items():
        if len(c)>d:
            earlier=float(c.iloc[-1-d])
            rows.append({
                "Period":label,
                "Earlier price":earlier,
                "Current price":current,
                "Price move":current-earlier,
                "Return %":(current/earlier-1)*100
            })
    return pd.DataFrame(rows)

def drawdown(c,days):
    w=c.iloc[-min(days,len(c)):]
    return (float(c.iloc[-1])/float(w.max())-1)*100

def score(df):
    c=df["Close"]
    vals={k:(float(c.iloc[-1])/float(c.iloc[-1-d])-1)*100 for k,d in PERIODS.items() if len(c)>d}
    sc=0
    if vals["1D"]<=-6: sc+=12
    if vals["5D"]<=-10: sc+=14
    if vals["1M"]<=-15: sc+=14
    if drawdown(c,63)<=-20: sc+=18
    rv=float(rsi(c).iloc[-1])
    if rv<30: sc+=10
    elif rv<40: sc+=5
    return min(sc,100), vals, rv

def verdict(sc):
    if sc>=80:return "HIGH-PRIORITY REVIEW"
    if sc>=65:return "STRONG SETUP"
    if sc>=50:return "INTERESTING"
    if sc>=35:return "WATCH"
    return "NORMAL"

def chart(df,ticker):
    fig=go.Figure()
    fig.add_trace(go.Candlestick(
        x=df.index,
        open=df["Open"],high=df["High"],low=df["Low"],close=df["Close"],
        name=ticker
    ))
    fig.add_trace(go.Scatter(x=df.index,y=df["Close"].rolling(50).mean(),mode="lines",name="50DMA"))
    fig.add_trace(go.Scatter(x=df.index,y=df["Close"].rolling(200).mean(),mode="lines",name="200DMA"))
    fig.update_layout(
        height=520,
        margin=dict(l=10,r=10,t=30,b=10),
        xaxis=dict(
            rangeselector=dict(buttons=[
                dict(count=1,label="1M",step="month",stepmode="backward"),
                dict(count=3,label="3M",step="month",stepmode="backward"),
                dict(count=6,label="6M",step="month",stepmode="backward"),
                dict(count=1,label="1Y",step="year",stepmode="backward"),
                dict(count=2,label="2Y",step="year",stepmode="backward"),
                dict(count=5,label="5Y",step="year",stepmode="backward"),
                dict(step="all",label="MAX")
            ]),
            rangeslider=dict(visible=True),
            type="date"
        ),
        yaxis_title="Price ($)",
        legend=dict(orientation="h")
    )
    return fig

st.title("Mega-Cap Dip Radar v3")
st.caption("Short-term moves, longer-term drawdowns, and interactive charts.")

summary=[]
details={}

for t in WATCHLIST:
    df=load(t)
    if df.empty or len(df)<260:
        continue
    sc, vals, rv=score(df)
    c=df["Close"]
    summary.append({
        "Ticker":t,
        "Price":float(c.iloc[-1]),
        "1D":vals["1D"],"2D":vals["2D"],"5D":vals["5D"],"7D":vals["7D"],"10D":vals["10D"],
        "1M":vals["1M"],"3M":vals["3M"],"6M":vals["6M"],"12M":vals["12M"],
        "3M DD":drawdown(c,63),"6M DD":drawdown(c,126),"12M DD":drawdown(c,252),
        "RSI":rv,"Score":sc,"Verdict":verdict(sc)
    })
    details[t]=df

sumdf=pd.DataFrame(summary).sort_values(["Score","3M DD"],ascending=[False,True])

st.subheader("Sniper board")
fmt={c:"{:.1f}%" for c in ["1D","2D","5D","7D","10D","1M","3M","6M","12M","3M DD","6M DD","12M DD"]}
fmt["Price"]="${:,.2f}"
fmt["RSI"]="{:.0f}"
fmt["Score"]="{:.0f}"
st.dataframe(sumdf.style.format(fmt),use_container_width=True,hide_index=True)

if not sumdf.empty:
    top=sumdf.iloc[0]
    st.info(f'Highest-priority setup: {top["Ticker"]} · {top["Verdict"]} · score {top["Score"]}/100.')

st.subheader("Stock detail")
tabs=st.tabs(WATCHLIST)

for tab,t in zip(tabs,WATCHLIST):
    if t not in details:
        continue
    with tab:
        df=details[t]
        row=sumdf[sumdf["Ticker"]==t].iloc[0]

        a,b,c,d=st.columns(4)
        a.metric("Current price",f'${row["Price"]:,.2f}')
        b.metric("Score",f'{row["Score"]}/100')
        c.metric("3M drawdown",f'{row["3M DD"]:.1f}%')
        d.metric("RSI",f'{row["RSI"]:.0f}')

        st.markdown("#### Price movement by period")
        moves=period_table(df)
        st.dataframe(
            moves.style.format({
                "Earlier price":"${:,.2f}",
                "Current price":"${:,.2f}",
                "Price move":"${:+,.2f}",
                "Return %":"{:+.1f}%"
            }),
            hide_index=True,
            use_container_width=True
        )

        st.markdown("#### Interactive chart")
        st.plotly_chart(chart(df,t),use_container_width=True)

st.caption("Research tool only. Historical price behaviour does not guarantee future returns.")

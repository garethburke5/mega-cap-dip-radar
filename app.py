
import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta, timezone

st.set_page_config(page_title="Mega-Cap Dip Radar v2", page_icon="🎯", layout="wide")

WATCHLIST = ["TSLA","NVDA","META","AMZN","GOOGL"]
PERIODS = {"1D":1,"2D":2,"5D":5,"7D":7,"10D":10,"1M":21,"3M":63,"6M":126,"12M":252}
MATCH_COLS = ["1D","5D","10D","1M","3M_DD","6M_DD","RSI","Dist50"]

@st.cache_data(ttl=300)
def load(ticker, years=10):
    end = datetime.now(timezone.utc).date() + timedelta(days=1)
    start = end - timedelta(days=int(years*365.25)+30)
    df = yf.download(ticker, start=start, end=end, auto_adjust=True, progress=False)
    if df.empty:
        return df
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df[["Close","Volume"]].dropna()

def rsi(s, n=14):
    d=s.diff()
    g=d.clip(lower=0).rolling(n).mean()
    l=-d.clip(upper=0).rolling(n).mean()
    rs=g/l.replace(0,np.nan)
    return 100-(100/(1+rs))

def ret(s,d,i=None):
    if i is None: i=len(s)-1
    if i-d < 0: return np.nan
    return (s.iloc[i]/s.iloc[i-d]-1)*100

def dd(s,days,i=None):
    if i is None: i=len(s)-1
    a=max(0,i-days+1)
    h=s.iloc[a:i+1].max()
    return (s.iloc[i]/h-1)*100

def features(df):
    c=df["Close"]
    out=pd.DataFrame(index=df.index)
    for k,d in PERIODS.items():
        out[k]=c.pct_change(d)*100
    out["3M_DD"]=c/c.rolling(63).max()*100-100
    out["6M_DD"]=c/c.rolling(126).max()*100-100
    out["12M_DD"]=c/c.rolling(252).max()*100-100
    out["RSI"]=rsi(c)
    out["Dist50"]=(c/c.rolling(50).mean()-1)*100
    out["VolRatio"]=df["Volume"]/df["Volume"].rolling(20).mean()
    return out

def closest_matches(df, n=8, gap=40):
    f=features(df).dropna()
    if len(f)<350:
        return pd.DataFrame(), f

    today=f.iloc[-1]
    hist=f.iloc[:-30].copy()
    dist=pd.Series(0.0,index=hist.index)
    used=0
    for col in MATCH_COLS:
        sd=hist[col].std()
        if pd.notna(sd) and sd>0:
            dist += ((hist[col]-today[col])/sd)**2
            used += 1
    dist=np.sqrt(dist/max(used,1)).sort_values()

    picked=[]
    picked_pos=[]
    for dt,val in dist.items():
        pos=df.index.get_loc(dt)
        if all(abs(pos-p)>=gap for p in picked_pos):
            picked.append((dt,float(val),pos))
            picked_pos.append(pos)
        if len(picked)>=n:
            break

    rows=[]
    c=df["Close"]
    for dt,distance,pos in picked:
        entry=float(c.iloc[pos])
        future=c.iloc[pos+1:min(len(c),pos+127)]
        if future.empty: continue
        best=(future.max()/entry-1)*100
        worst=(future.min()/entry-1)*100

        d10=d20=None
        for j in range(pos+1,min(len(c),pos+253)):
            rr=(c.iloc[j]/entry-1)*100
            if d10 is None and rr>=10: d10=j-pos
            if d20 is None and rr>=20: d20=j-pos
            if d10 is not None and d20 is not None: break

        rows.append({
            "Date":dt.date(),
            "Similarity":distance,
            "Best next 6M %":best,
            "Worst next 6M %":worst,
            "Days to +10%":d10,
            "Days to +20%":d20
        })
    return pd.DataFrame(rows), f

def score(row, matches, rel5):
    s=0
    if row["1D"]<=-7: s+=12
    elif row["1D"]<=-4: s+=7
    if row["5D"]<=-12: s+=14
    elif row["5D"]<=-8: s+=9
    if row["1M"]<=-18: s+=14
    elif row["1M"]<=-10: s+=8
    if row["3M_DD"]<=-30: s+=18
    elif row["3M_DD"]<=-20: s+=12
    elif row["3M_DD"]<=-12: s+=6
    if rel5<=-5: s+=7
    if row["RSI"]<30: s+=10
    elif row["RSI"]<40: s+=5
    if row["VolRatio"]>=1.5: s+=5
    if len(matches)>=4:
        p20=matches["Days to +20%"].notna().mean()
        medbest=matches["Best next 6M %"].median()
        if p20>=0.65: s+=10
        elif p20>=0.5: s+=6
        if medbest>=20: s+=5
    return min(100,int(round(s)))

def verdict(sc):
    if sc>=80:return "HIGH-PRIORITY REVIEW"
    if sc>=65:return "STRONG SETUP"
    if sc>=50:return "INTERESTING"
    if sc>=35:return "WATCH"
    return "NORMAL"

qqq=load("QQQ",10)
spy=load("SPY",10)
qqq5=ret(qqq["Close"],5) if not qqq.empty else np.nan
spy5=ret(spy["Close"],5) if not spy.empty else np.nan

st.title("Mega-Cap Dip Radar v2")
st.caption("Short-term shock + longer-term drawdown + market-relative weakness + historical pattern matching.")

summary=[]
details={}

for t in WATCHLIST:
    df=load(t,10)
    if df.empty or len(df)<350:
        continue

    f=features(df).dropna()
    cur=f.iloc[-1].copy()
    rel5=cur["5D"]-qqq5
    matches,_=closest_matches(df)

    sc=score(cur,matches,rel5)

    row={"Ticker":t,"Price":float(df["Close"].iloc[-1])}
    for p in PERIODS:
        row[p]=cur[p]
    row.update({
        "3M DD":cur["3M_DD"],
        "6M DD":cur["6M_DD"],
        "12M DD":cur["12M_DD"],
        "Rel vs QQQ 5D":rel5,
        "RSI":cur["RSI"],
        "Volume x":cur["VolRatio"],
        "Score":sc,
        "Verdict":verdict(sc)
    })
    summary.append(row)
    details[t]=(df,cur,matches,rel5)

sumdf=pd.DataFrame(summary).sort_values(["Score","3M DD"],ascending=[False,True])

st.subheader("Sniper board")
cols=["Ticker","Price","1D","2D","5D","7D","10D","1M","3M","6M","12M",
      "3M DD","6M DD","12M DD","Rel vs QQQ 5D","RSI","Score","Verdict"]
fmt={c:"{:.1f}%" for c in ["1D","2D","5D","7D","10D","1M","3M","6M","12M",
                            "3M DD","6M DD","12M DD","Rel vs QQQ 5D"]}
fmt["Price"]="${:,.2f}"
fmt["RSI"]="{:.0f}"
fmt["Score"]="{:.0f}"
st.dataframe(sumdf[cols].style.format(fmt),use_container_width=True,hide_index=True)

top=sumdf.iloc[0]
st.info(f'Highest-priority setup: {top["Ticker"]} · {top["Verdict"]} · score {top["Score"]}/100.')

st.subheader("Historical pattern engine")
tabs=st.tabs(WATCHLIST)

for tab,t in zip(tabs,WATCHLIST):
    if t not in details: continue
    with tab:
        df,cur,matches,rel5=details[t]
        row=sumdf[sumdf["Ticker"]==t].iloc[0]

        c1,c2,c3,c4=st.columns(4)
        c1.metric("Price",f'${row["Price"]:,.2f}')
        c2.metric("Score",f'{row["Score"]}/100')
        c3.metric("3M drawdown",f'{row["3M DD"]:.1f}%')
        c4.metric("5D vs QQQ",f'{row["Rel vs QQQ 5D"]:.1f}%')

        st.markdown("#### Recent price behaviour")
        temp=pd.DataFrame({"Period":list(PERIODS.keys()),"Return %":[cur[p] for p in PERIODS]})
        st.dataframe(temp.style.format({"Return %":"{:.1f}%"}),hide_index=True,use_container_width=True)

        st.markdown("#### Closest historical setups")
        if matches.empty:
            st.warning("Not enough historical matches.")
        else:
            st.dataframe(matches.style.format({
                "Similarity":"{:.2f}",
                "Best next 6M %":"{:.1f}%",
                "Worst next 6M %":"{:.1f}%"
            }),hide_index=True,use_container_width=True)

            medbest=matches["Best next 6M %"].median()
            medworst=matches["Worst next 6M %"].median()
            p20=matches["Days to +20%"].notna().mean()*100
            meddays=matches["Days to +20%"].median() if matches["Days to +20%"].notna().any() else np.nan

            a,b,c,d=st.columns(4)
            a.metric("Median best 6M",f"{medbest:.1f}%")
            b.metric("Median worst 6M",f"{medworst:.1f}%")
            c.metric("Reached +20%",f"{p20:.0f}%")
            d.metric("Median days to +20%",f"{meddays:.0f}" if pd.notna(meddays) else "N/A")

            downside=abs(medworst)
            rr=medbest/downside if downside>0 else np.nan
            st.write(
                f"Historical trade profile: median best 6-month move {medbest:.1f}%, "
                f"median adverse move {downside:.1f}%"
                + (f", indicative reward/risk about {rr:.1f}:1." if pd.notna(rr) else ".")
            )

        st.markdown("#### Market context")
        st.write(
            f'{t} 5D: {cur["5D"]:.1f}% · QQQ 5D: {qqq5:.1f}% · '
            f'SPY 5D: {spy5:.1f}% · relative to QQQ: {rel5:.1f}%'
        )

st.divider()
st.caption("Historical similarity is descriptive, not predictive. Use this to focus research, not to trade automatically.")

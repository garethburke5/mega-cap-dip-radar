
import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import numpy as np
import yfinance as yf
import json, math, html
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from streamlit_autorefresh import st_autorefresh

st.set_page_config(page_title="Share Sniper", page_icon="🎯", layout="wide")

st_autorefresh(interval=5 * 60 * 1000, limit=None, key="five_minute_refresh")

WATCHLIST = ["TSLA","NVDA","META","AMZN","GOOGL","AVGO","BARC.L","QCOM","BA","SPCX"]
COMPANY_NAMES = {
    "TSLA":"Tesla",
    "NVDA":"Nvidia",
    "META":"Meta",
    "AMZN":"Amazon",
    "GOOGL":"Alphabet (Google)",
    "AVGO":"Broadcom",
    "BARC.L":"Barclays",
    "QCOM":"Qualcomm",
    "BA":"Boeing",
    "SPCX":"SpaceX",
}

SNIPER_PROFILES = {
    "TSLA":"Core wave share — frequent large swings. Entry discipline still matters.",
    "NVDA":"Core wave share — repeated large corrections and rebounds.",
    "META":"Core wave share — meaningful sentiment-driven falls and recoveries.",
    "AMZN":"Core wave share — regular enough corrections to suit the rebound strategy.",
    "GOOGL":"Core wave share — somewhat calmer, but still produces meaningful corrections.",
    "AVGO":"High-volatility candidate — keep, but require stronger evidence that the fall has stabilised because false bottoms can occur.",
    "BARC.L":"UK blue-chip wave share — banking and macro moves can create meaningful corrections and rebounds.",
    "QCOM":"Occasional deep-dip candidate — most interesting after a genuinely large fall. Around $140–$150 is a particularly interesting area to investigate if the business remains sound.",
    "BA":"Occasional deep-dip candidate — only interesting after a substantial collapse. Company-specific risk is higher, so always check why the share has fallen before buying.",
    "SPCX":"Full Sniper analysis + new-listing intelligence — potentially exceptional rebound amplitude. Use the same price, RSI, dip, entry, market, news and fundamental analysis as every other share, plus extra IPO/unlock/event context because the trading history is short.",
}

def display_price(ticker, price):
    return f"{price:,.1f}p" if ticker.endswith(".L") else f"${price:,.2f}"

PERIODS = {"1D":1,"2D":2,"5D":5,"7D":7,"10D":10,"1M":21,"3M":63,"6M":126,"12M":252}
MATCH_FEATURES = ["1D","5D","10D","1M","3M_DD","6M_DD","RSI","DIST50","VOLRATIO"]

# ---------- DATA ----------
@st.cache_data(ttl=300)
def load_price(ticker, years=10):
    end = datetime.now(timezone.utc).date() + timedelta(days=1)
    start = end - timedelta(days=int(years*365.25)+90)
    df = yf.download(ticker, start=start, end=end, auto_adjust=True, progress=False, threads=False)
    if df.empty:
        return df
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    cols=[c for c in ["Open","High","Low","Close","Volume"] if c in df.columns]
    return df[cols].dropna()

@st.cache_data(ttl=120)
def load_intraday(ticker):
    try:
        df = yf.download(
            ticker, period="5d", interval="5m",
            auto_adjust=True, progress=False, prepost=False, threads=False
        )
        if df.empty:
            return None, None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        close = df["Close"].dropna()
        if close.empty:
            return None, None
        px = float(close.iloc[-1])
        ts = close.index[-1]
        try:
            if ts.tzinfo is None:
                ts = ts.tz_localize("America/New_York")
            else:
                ts = ts.tz_convert("America/New_York")
        except Exception:
            pass
        return px, ts
    except Exception:
        return None, None

def us_market_status():
    now_ny = datetime.now(ZoneInfo("America/New_York"))
    weekday = now_ny.weekday() < 5
    mins = now_ny.hour * 60 + now_ny.minute
    regular = weekday and (9*60+30 <= mins < 16*60)
    return ("OPEN" if regular else "CLOSED"), now_ny

@st.cache_data(ttl=1800)
def load_fundamentals(ticker):
    try:
        tk=yf.Ticker(ticker)
        info=tk.info or {}
        return {
            "marketCap":info.get("marketCap"),
            "trailingPE":info.get("trailingPE"),
            "forwardPE":info.get("forwardPE"),
            "priceToSalesTrailing12Months":info.get("priceToSalesTrailing12Months"),
            "revenueGrowth":info.get("revenueGrowth"),
            "earningsGrowth":info.get("earningsGrowth"),
            "profitMargins":info.get("profitMargins"),
            "freeCashflow":info.get("freeCashflow"),
            "targetMeanPrice":info.get("targetMeanPrice"),
            "recommendationKey":info.get("recommendationKey"),
            "numberOfAnalystOpinions":info.get("numberOfAnalystOpinions"),
        }
    except Exception:
        return {}

@st.cache_data(ttl=900)
def load_news(ticker):
    try:
        raw=yf.Ticker(ticker).news or []
        rows=[]
        for x in raw[:10]:
            c=x.get("content",x)
            title=c.get("title") or x.get("title")
            summary=c.get("summary") or c.get("description") or ""
            provider=c.get("provider",{})
            publisher=provider.get("displayName","") if isinstance(provider,dict) else ""
            url=""
            click=c.get("clickThroughUrl")
            canon=c.get("canonicalUrl")
            if isinstance(click,dict): url=click.get("url","")
            if not url and isinstance(canon,dict): url=canon.get("url","")
            if title:
                rows.append({"title":title,"summary":summary,"publisher":publisher,"url":url})
        return rows
    except Exception:
        return []

# ---------- METRICS ----------
def calc_rsi(s,n=14):
    d=s.diff()
    gain=d.clip(lower=0).ewm(alpha=1/n,adjust=False).mean()
    loss=-d.clip(upper=0).ewm(alpha=1/n,adjust=False).mean()
    rs=gain/loss.replace(0,np.nan)
    return 100-(100/(1+rs))

def feature_frame(df):
    c=df["Close"]
    f=pd.DataFrame(index=df.index)
    for k,d in PERIODS.items():
        f[k]=c.pct_change(d)*100

    # Standard rolling drawdowns for mature shares.
    f["3M_DD"]=(c/c.rolling(63).max()-1)*100
    f["6M_DD"]=(c/c.rolling(126).max()-1)*100
    f["12M_DD"]=(c/c.rolling(252).max()-1)*100

    # New listings do not yet have 63/126/252 trading days.
    # Use the available public-history peak so they still receive full analysis.
    running_high=c.cummax()
    public_dd=(c/running_high-1)*100
    if len(c) < 63:
        f["3M_DD"]=public_dd
    if len(c) < 126:
        f["6M_DD"]=public_dd
    if len(c) < 252:
        f["12M_DD"]=public_dd

    f["RSI"]=calc_rsi(c)

    # Use all available days until 50 trading days exist.
    ma50=c.rolling(50, min_periods=min(10,len(c))).mean()
    f["DIST50"]=(c/ma50-1)*100
    f["VOLRATIO"]=df["Volume"]/df["Volume"].rolling(20,min_periods=min(5,len(c))).mean()
    return f

def percentile_rank(series,value,lower_is_extreme=True):
    s=series.dropna()
    if s.empty:return np.nan
    if lower_is_extreme:
        return float((s<=value).mean()*100)
    return float((s>=value).mean()*100)

def period_rows(df,f):
    c=df["Close"]; now=float(c.iloc[-1])
    out=[]
    for label,d in PERIODS.items():
        if len(c)>d:
            was=float(c.iloc[-1-d]); move=now-was; pct=(now/was-1)*100
            hist=f[label].iloc[:-1].dropna()
            tail=percentile_rank(hist,pct,True) if pct<0 else percentile_rank(hist,pct,False)
            if pct <= -10: meaning="Sharp sell-off"
            elif pct <= -5: meaning="Meaningful decline"
            elif pct <= -2: meaning="Moderate decline"
            elif pct < 2: meaning="Broadly flat"
            elif pct < 5: meaning="Rising"
            elif pct < 10: meaning="Strong rebound"
            else: meaning="Very sharp rebound"
            out.append({"Period":label,"Was":was,"Now":now,"Move":move,"Change %":pct,
                        "Meaning":meaning,"Tail percentile":tail})
    return pd.DataFrame(out)

# ---------- HISTORICAL ANALOGUES ----------
def historical_matches(df,f,n=10,gap=42):
    clean=f.dropna()
    if len(clean)<400:return pd.DataFrame()
    cur=clean.iloc[-1]
    hist=clean.iloc[:-30].copy()
    distance=pd.Series(0.0,index=hist.index)
    used=0
    for col in MATCH_FEATURES:
        sd=hist[col].std()
        if pd.notna(sd) and sd>0:
            distance += ((hist[col]-cur[col])/sd)**2
            used+=1
    distance=np.sqrt(distance/max(used,1)).sort_values()
    chosen=[]; positions=[]
    for dt,dist in distance.items():
        pos=df.index.get_loc(dt)
        if all(abs(pos-p)>=gap for p in positions):
            chosen.append((dt,float(dist),pos)); positions.append(pos)
        if len(chosen)>=n:break

    c=df["Close"]; rows=[]
    for dt,dist,pos in chosen:
        entry=float(c.iloc[pos])
        full6m = (pos+126) < len(c)
        fut6 = c.iloc[pos+1:pos+127] if full6m else pd.Series(dtype=float)
        best=float((fut6.max()/entry-1)*100) if full6m and not fut6.empty else np.nan
        worst=float((fut6.min()/entry-1)*100) if full6m and not fut6.empty else np.nan
        returns={}
        for lab,d in [("1M",21),("3M",63),("6M",126)]:
            returns[lab]=float((c.iloc[pos+d]/entry-1)*100) if pos+d<len(c) else np.nan
        days={}
        full1y = (pos+252) < len(c)
        for threshold in [10,20,30]:
            hit=None
            if full1y:
                for j in range(pos+1,pos+253):
                    if (float(c.iloc[j])/entry-1)*100>=threshold:
                        hit=j-pos;break
            days[threshold]=hit
        rows.append({
            "Date":dt.date(),"Similarity":dist,"1M %":returns["1M"],"3M %":returns["3M"],
            "6M %":returns["6M"],"Best 6M %":best,"Further downside %":worst,
            "Days +10%":days[10],"Days +20%":days[20],"Days +30%":days[30],
            "Full 1Y history":full1y,
            "Low proximity %":abs(worst) if pd.notna(worst) else np.nan
        })
    return pd.DataFrame(rows)

def hist_summary(matches,current_price):
    if matches.empty:return {}
    v1=matches["1M %"].dropna()
    v3=matches["3M %"].dropna()
    v6=matches["6M %"].dropna()
    full6=matches.dropna(subset=["6M %","Further downside %"])
    full1y=matches[matches.get("Full 1Y history",False)==True] if "Full 1Y history" in matches.columns else matches.iloc[0:0]
    med1=v1.median() if len(v1) else np.nan
    med3=v3.median() if len(v3) else np.nan
    med6=v6.median() if len(v6) else np.nan
    medbest=full6["Best 6M %"].median() if len(full6) else np.nan
    meddown=full6["Further downside %"].median() if len(full6) else np.nan
    p10=full1y["Days +10%"].notna().mean()*100 if len(full1y) else np.nan
    p20=full1y["Days +20%"].notna().mean()*100 if len(full1y) else np.nan
    p30=full1y["Days +30%"].notna().mean()*100 if len(full1y) else np.nan
    enough6 = len(v6) >= 5
    target_pct = med6 if enough6 and pd.notna(med6) and med6 > 0 else np.nan
    return {
        "n":len(matches),"n1":len(v1),"n3":len(v3),"n6":len(v6),"n1y":len(full1y),
        "med1":med1,"med3":med3,"med6":med6,"medbest":medbest,
        "meddown":meddown,"p10":p10,"p20":p20,"p30":p30,
        "target":current_price*(1+target_pct/100) if pd.notna(target_pct) else np.nan,
        "target_pct":target_pct,
        "adverse":current_price*(1+meddown/100) if pd.notna(meddown) else np.nan,
        "rr": target_pct/abs(meddown) if pd.notna(target_pct) and pd.notna(meddown) and meddown<0 else np.nan
    }

# ---------- INTERPRETATION ----------
def fundamental_assessment(info,current_price):
    points=0; notes=[]
    rg=info.get("revenueGrowth"); eg=info.get("earningsGrowth"); pm=info.get("profitMargins")
    target=info.get("targetMeanPrice")
    if isinstance(rg,(int,float)):
        if rg>0.10: points+=2; notes.append(f"revenue growth {rg*100:.1f}%")
        elif rg>0: points+=1; notes.append(f"revenue growth {rg*100:.1f}%")
        else: points-=2; notes.append(f"revenue growth {rg*100:.1f}%")
    if isinstance(eg,(int,float)):
        if eg>0.10: points+=2; notes.append(f"earnings growth {eg*100:.1f}%")
        elif eg<0: points-=2; notes.append(f"earnings growth {eg*100:.1f}%")
    if isinstance(pm,(int,float)):
        if pm>0.15: points+=1
        elif pm<0: points-=2
    if isinstance(target,(int,float)) and target>0:
        upside=(target/current_price-1)*100
        notes.append(f"analyst mean target implies {upside:+.1f}%")
        if upside>15:points+=1
        elif upside<-5:points-=1
    if points>=4: label="STRONG"
    elif points>=1: label="STABLE"
    elif points>=-1: label="MIXED"
    else: label="DETERIORATING"
    return label,notes

def opportunity_engine(df,f,matches,bench5,fund_label):
    cur=f.iloc[-1]; c=df["Close"]; now=float(c.iloc[-1])
    d3=float(cur["3M_DD"]); d6=float(cur["6M_DD"]); r1=float(cur["1D"]); r5=float(cur["5D"]); r10=float(cur["10D"])
    rsi=float(cur["RSI"]); rel5=float(cur["5D"]-bench5) if pd.notna(bench5) else np.nan
    hs=hist_summary(matches,now)

    score=0; reasons=[]; cautions=[]
    # severity
    if d3<=-30:score+=22; reasons.append("extreme 3-month correction")
    elif d3<=-20:score+=17; reasons.append("major 3-month correction")
    elif d3<=-12:score+=9; reasons.append("meaningful 3-month correction")
    # acute shock
    if r5<=-12:score+=12; reasons.append("unusually sharp 5-day sell-off")
    elif r5<=-7:score+=7; reasons.append("significant 5-day weakness")
    # reversal
    if d3<=-12 and r5>3:score+=12; reasons.append("short-term rebound after a larger correction")
    if d3<=-12 and r10>5:score+=8
    # momentum
    if rsi<30:score+=10; reasons.append("RSI is in conventionally oversold territory")
    elif rsi<40:score+=5; reasons.append("momentum remains weak, leaving room for recovery")
    elif rsi>70:score-=6; cautions.append("RSI is already elevated")
    # relative
    if pd.notna(rel5) and rel5<=-5:score+=5; reasons.append("stock-specific weakness exceeds the Nasdaq")
    # history
    if hs:
        if pd.notna(hs["p20"]) and hs["n1y"]>=5 and hs["p20"]>=70:
            score+=12; reasons.append("completed historical cases often later rose at least 20%")
        elif pd.notna(hs["p20"]) and hs["n1y"]>=5 and hs["p20"]>=50:
            score+=7; reasons.append("completed historical cases are moderately favourable")
        elif pd.notna(hs["p20"]) and hs["n1y"]>=5:
            cautions.append("completed historical cases have a weaker +20% recovery rate")
        if pd.notna(hs["rr"]) and hs["rr"]>=2.5:score+=7; reasons.append("historical reward/risk is attractive")
        if pd.notna(hs["meddown"]) and hs["meddown"]<-15:cautions.append("completed similar episodes often suffered substantial further downside")
    # fundamentals
    if fund_label=="STRONG":score+=6; reasons.append("fundamental snapshot remains strong")
    elif fund_label=="DETERIORATING":score-=10; cautions.append("fundamental snapshot is deteriorating")

    score=int(max(0,min(100,round(score))))
    reversal=(r5>2 and r10>3)
    if score>=80 and reversal: status="HIGH-PRIORITY ENTRY REVIEW"; action="Investigate entry now"
    elif score>=65 and reversal: status="ENTRY DEVELOPING"; action="Investigate entry"
    elif d3<=-20 and not reversal: status="DEEP SELLOFF"; action="Watch for stabilisation"
    elif d3<=-12 and reversal: status="REVERSAL DEVELOPING"; action="Watch closely / investigate entry"
    elif score>=40: status="WATCH"; action="Keep on watchlist"
    else: status="NORMAL"; action="No action"

    if d3<=-12 and r5>3:
        narrative=f"The share is still in a substantial medium-term correction ({d3:.1f}% from its 3-month high), but has risen {r5:.1f}% over the last five trading days. That combination suggests selling pressure may be easing and a reversal could be developing."
    elif r5<-5:
        narrative=f"The share is falling quickly: {r5:.1f}% over five trading days. The move may be creating an opportunity, but the price has not yet shown convincing evidence of stabilising."
    elif d3<=-12:
        narrative=f"The share remains {abs(d3):.1f}% below its 3-month high, but short-term price action is not yet strong enough to classify this as a confirmed reversal."
    else:
        narrative="There is no unusually deep correction/reversal combination at present."

    return {"score":score,"status":status,"action":action,"reasons":reasons[:6],
            "cautions":cautions[:4],"narrative":narrative,"rel5":rel5}


def score_explanation(score):
    if score < 30:
        return "LOW INTEREST", "There is not enough evidence of an unusually attractive buying opportunity at the moment.", "IGNORE FOR NOW"
    if score < 50:
        return "WATCH", "There are some encouraging signs, but the evidence for buying is still fairly weak.", "WATCH"
    if score < 65:
        return "INTERESTING", "The setup is becoming interesting. It is worth investigating more closely, but it is not yet one of the strongest signals.", "INVESTIGATE"
    if score < 80:
        return "STRONG OPPORTUNITY", "Several useful signals are lining up. This deserves serious investigation as a possible entry.", "INVESTIGATE BUY"
    return "EXCEPTIONAL SETUP", "This is one of the strongest combinations of sell-off, recovery evidence and historical support detected by the model.", "HIGHEST PRIORITY"

def rsi_explanation(rsi, rsi_5d_ago=np.nan):
    if rsi < 20:
        label="EXTREMELY OVERSOLD"
        meaning="The share has been under exceptionally heavy selling pressure. That can create opportunity, but it can also mean the fall is not finished."
    elif rsi < 30:
        label="IDEAL DIP-WATCH AREA"
        meaning="The share is in the traditional oversold area. This is interesting for our dip strategy, especially if the price starts rising."
    elif rsi < 40:
        label="INTERESTING"
        meaning="Momentum is still weak after the fall. This can be useful if the RSI and share price are beginning to rise together."
    elif rsi < 60:
        label="NEUTRAL"
        meaning="Momentum is neither especially weak nor especially strong."
    elif rsi < 70:
        label="STRONG"
        meaning="The share already has fairly strong upward momentum, so it is less like the early dip-buying setup we are hunting."
    else:
        label="VERY STRONG / POSSIBLY OVERBOUGHT"
        meaning="The share has risen strongly. For our dip-buying strategy this is usually less attractive than a low RSI."
    direction=""
    if pd.notna(rsi_5d_ago):
        if rsi_5d_ago < 35 and rsi > rsi_5d_ago + 3:
            direction=f" RSI has risen from {rsi_5d_ago:.0f} five trading days ago, which is encouraging because selling momentum may be easing."
        elif rsi < rsi_5d_ago - 3:
            direction=f" RSI has fallen from {rsi_5d_ago:.0f} five trading days ago, so selling momentum is still worsening."
    return label, meaning + direction

def recent_levels(df, days=63):
    recent=df.tail(days)
    peak=float(recent["Close"].max())
    low=float(recent["Close"].min())
    return peak,low

def entry_zone(df,f,matches):
    price=float(df["Close"].iloc[-1])
    cur=f.iloc[-1]
    rsi=float(cur["RSI"])
    hs=hist_summary(matches,price)
    # A reference zone, not an instruction: near current/recent support when RSI is weak.
    low63=float(df["Close"].tail(63).min())
    ma20=float(df["Close"].tail(20).mean())
    if rsi <= 35:
        upper=min(price, ma20) if ma20 < price else price
        lower=max(low63, upper*0.94)
        note="This is an area to investigate, not an automatic buy range. It is based on recent support, current price and weak RSI."
        return lower,upper,note
    if cur["3M_DD"] <= -12:
        upper=price*0.97
        lower=max(low63,price*0.90)
        note="RSI is not yet in our preferred dip-buying area, so the app would prefer either a cheaper price or clearer recovery evidence."
        return lower,upper,note
    return np.nan,np.nan,"No useful dip-entry zone is identified at the moment."


def rebound_strategy_snapshot(df, matches, stake_gbp=20000):
    price=float(df["Close"].iloc[-1])
    c=df["Close"]

    peak1=float(c.tail(21).max())
    peak3=float(c.tail(63).max())
    peak6=float(c.tail(126).max())
    low21=float(c.tail(21).min())
    low63=float(c.tail(63).min())

    target10=price*1.10
    target20=price*1.20

    full1y = matches[matches["Full 1Y history"]==True].copy() if (not matches.empty and "Full 1Y history" in matches.columns) else pd.DataFrame()
    n=len(full1y)
    hit10=int(full1y["Days +10%"].notna().sum()) if n else 0
    hit20=int(full1y["Days +20%"].notna().sum()) if n else 0
    p10=hit10/n*100 if n else np.nan
    p20=hit20/n*100 if n else np.nan
    d10=full1y["Days +10%"].dropna().median() if n else np.nan
    d20=full1y["Days +20%"].dropna().median() if n else np.nan

    full6 = matches.dropna(subset=["Further downside %"]) if not matches.empty else pd.DataFrame()
    meddown=full6["Further downside %"].median() if len(full6) else np.nan

    dd1=(price/peak1-1)*100
    dd3=(price/peak3-1)*100
    dd6=(price/peak6-1)*100
    bounce21=(price/low21-1)*100 if low21 else np.nan
    bounce63=(price/low63-1)*100 if low63 else np.nan
    r5=(price/float(c.iloc[-6])-1)*100 if len(c)>5 else np.nan
    r10=(price/float(c.iloc[-11])-1)*100 if len(c)>10 else np.nan
    rsi=float(calc_rsi(c).iloc[-1])

    # 1) DIP QUALITY: how unusually discounted is the stock?
    depth=max(abs(min(dd3,0)), abs(min(dd6,0)))
    dip_quality=0
    if depth >= 30: dip_quality=95
    elif depth >= 25: dip_quality=88
    elif depth >= 20: dip_quality=80
    elif depth >= 15: dip_quality=68
    elif depth >= 10: dip_quality=52
    elif depth >= 7: dip_quality=38
    else: dip_quality=20

    # 2) ENTRY QUALITY TODAY: dominant decision score.
    entry=50

    # Discount from recent highs helps entry quality.
    if dd3 <= -25: entry += 20
    elif dd3 <= -20: entry += 16
    elif dd3 <= -15: entry += 11
    elif dd3 <= -10: entry += 5
    elif dd3 > -5: entry -= 15

    # RSI: low can help, high hurts.
    if rsi < 25: entry += 10
    elif rsi < 35: entry += 7
    elif rsi < 45: entry += 3
    elif rsi > 70: entry -= 12
    elif rsi > 60: entry -= 7

    # Strong "don't chase" penalties.
    chase_reasons=[]
    chase_penalty=0

    if pd.notna(bounce21):
        if bounce21 >= 20:
            chase_penalty += 28
            chase_reasons.append(f"already {bounce21:.1f}% above its 1-month low")
        elif bounce21 >= 15:
            chase_penalty += 20
            chase_reasons.append(f"already {bounce21:.1f}% above its 1-month low")
        elif bounce21 >= 10:
            chase_penalty += 12
            chase_reasons.append(f"already {bounce21:.1f}% above its 1-month low")
        elif bounce21 >= 7:
            chase_penalty += 7
            chase_reasons.append(f"already {bounce21:.1f}% above its 1-month low")

    if pd.notna(r5):
        if r5 >= 12:
            chase_penalty += 18
            chase_reasons.append(f"up {r5:.1f}% in 5 trading days")
        elif r5 >= 8:
            chase_penalty += 12
            chase_reasons.append(f"up {r5:.1f}% in 5 trading days")
        elif r5 >= 5:
            chase_penalty += 6
            chase_reasons.append(f"up {r5:.1f}% in 5 trading days")

    if pd.notna(r10):
        if r10 >= 18:
            chase_penalty += 16
            chase_reasons.append(f"up {r10:.1f}% in 10 trading days")
        elif r10 >= 12:
            chase_penalty += 10
            chase_reasons.append(f"up {r10:.1f}% in 10 trading days")

    entry -= chase_penalty

    # Historical evidence helps only modestly; it cannot overpower a bad entry.
    history_bonus=0
    if pd.notna(p10):
        history_bonus += 6 if p10>=70 else 3 if p10>=55 else -3 if p10<40 else 0
    if pd.notna(p20):
        history_bonus += 7 if p20>=60 else 4 if p20>=45 else -4 if p20<30 else 0
    if pd.notna(meddown):
        if meddown <= -20: history_bonus -= 8
        elif meddown <= -12: history_bonus -= 4
        elif meddown >= -7: history_bonus += 3

    entry += history_bonus

    # Hard caps so a rebound already underway cannot display as a strong entry.
    if dd3 > -5 and dd6 > -7:
        entry=min(entry,35)
    if bounce21 >= 15:
        entry=min(entry,55)
    elif bounce21 >= 10:
        entry=min(entry,62)
    if pd.notna(r5) and r5 >= 8:
        entry=min(entry,58)
    if pd.notna(r10) and r10 >= 12:
        entry=min(entry,58)

    entry_score=int(max(0,min(100,round(entry))))

    if entry_score >= 78:
        verdict="STRONG BUYING OPPORTUNITY"
        instinct="INVESTIGATE BUY"
    elif entry_score >= 63:
        verdict="POSSIBLE OPPORTUNITY — CHECK THE PRICE"
        instinct="INVESTIGATE"
    elif entry_score >= 48:
        verdict="WAIT — SEE IF THE PRICE FALLS FURTHER"
        instinct="WATCH"
    elif chase_penalty >= 12:
        verdict="WAIT — PRICE HAS ALREADY RISEN SHARPLY"
        instinct="WAIT"
    else:
        verdict="WAIT"
        instinct="WAIT"

    # If the broad dip is excellent but today's entry is weaker, say so explicitly.
    if dip_quality >= 80 and entry_score < 63:
        situation = "The overall dip is substantial, but today's price is not as attractive because the share has already bounced."
    elif dip_quality >= 70 and entry_score >= 63:
        situation = "The stock is still meaningfully discounted and today's entry remains reasonably attractive."
    elif dip_quality < 50:
        situation = "There is not a strong enough current dip for this strategy."
    else:
        situation = "The dip is interesting, but entry quality is mixed."

    if chase_reasons:
        entry_explain = "Why the buying score is lower: " + "; ".join(chase_reasons) + "."
        if entry_score < 63:
            entry_explain += " The recent dip was substantial, but the share has already bounced. Wait and see if the price falls further and gives you a better entry."
    else:
        entry_explain = "There has not yet been a large enough rebound to trigger the app's main 'don't chase' penalties."

    gap10=(target10/peak3-1)*100
    gap20=(target20/peak3-1)*100
    if target20 <= peak3:
        peak_context=f"A 20% rise from today would still leave the share {abs(gap20):.1f}% below its recent 3-month high of ${peak3:,.2f}."
    elif target10 <= peak3:
        peak_context=f"A 10% rise stays below the recent 3-month high, but +20% would require a new 3-month high."
    else:
        peak_context=f"Even +10% from today would require the share to exceed its recent 3-month high of ${peak3:,.2f}."

    return {
        "stake":stake_gbp,"target10":target10,"target20":target20,
        "gain10":stake_gbp*.10,"gain20":stake_gbp*.20,
        "peak3":peak3,"gap10":gap10,"gap20":gap20,"peak_context":peak_context,
        "n":n,"hit10":hit10,"hit20":hit20,"p10":p10,"p20":p20,
        "days10":d10,"days20":d20,"meddown":meddown,
        "score":entry_score,"entry_score":entry_score,"dip_quality":dip_quality,
        "verdict":verdict,"instinct":instinct,"summary":situation,
        "entry_explain":entry_explain,
        "dd1":dd1,"dd3":dd3,"dd6":dd6,"bounce21":bounce21,"bounce63":bounce63,
        "r5":r5,"r10":r10,"rsi":rsi,"chase_penalty":chase_penalty
    }

# ---------- NEWS ----------
def classify_news(news):
    text=" ".join((x["title"]+" "+x.get("summary","")).lower() for x in news[:8])
    cats=[]
    mapping={
        "EARNINGS / GUIDANCE":["earnings","guidance","revenue","profit","margin","forecast"],
        "REGULATORY / LEGAL":["regulator","regulatory","lawsuit","court","antitrust","probe","investigation"],
        "PRODUCT / AI":["ai","artificial intelligence","product","launch","chip","model"],
        "MACRO / MARKET":["fed","rates","inflation","tariff","market","nasdaq","economy"],
        "ANALYST / VALUATION":["analyst","upgrade","downgrade","target","valuation"]
    }
    for label,words in mapping.items():
        if any(w in text for w in words):cats.append(label)
    return cats[:3] if cats else ["UNCLEAR / MIXED"]


def period_return(df, days):
    if df is None or df.empty or len(df) <= days:
        return np.nan
    return (float(df["Close"].iloc[-1]) / float(df["Close"].iloc[-1-days]) - 1) * 100

def market_move_summary(stock_df, qqq_df, spy_df):
    rows=[]
    for label,days in [("1D",1),("5D",5),("1M",21),("3M",63)]:
        s=period_return(stock_df,days)
        q=period_return(qqq_df,days)
        p=period_return(spy_df,days)
        rows.append({"Period":label,"Stock":s,"Nasdaq-100 (QQQ)":q,"S&P 500 (SPY)":p,
                     "vs Nasdaq":s-q if pd.notna(s) and pd.notna(q) else np.nan})
    return pd.DataFrame(rows)

def market_move_interpretation(rows, ticker):
    if rows.empty:
        return "Not enough data to compare the share with the wider market."
    row5 = rows[rows["Period"]=="5D"].iloc[0] if not rows[rows["Period"]=="5D"].empty else rows.iloc[0]
    s=row5["Stock"]; q=row5["Nasdaq-100 (QQQ)"]
    if pd.isna(s) or pd.isna(q):
        return "Not enough data to determine whether the move is mostly market-wide or company-specific."
    diff=s-q
    if abs(diff) <= 2:
        return f"Most of {ticker}'s recent move appears broadly consistent with the wider technology market."
    if diff <= -5:
        return f"{ticker} has fallen much more than the Nasdaq-100, so a large part of the recent move appears company-specific. That deserves extra investigation before buying."
    if diff < -2:
        return f"{ticker} has been weaker than the Nasdaq-100, so the fall appears to be a mixture of a wider market move and company-specific weakness."
    if diff >= 5:
        return f"{ticker} has strongly outperformed the Nasdaq-100, so the recent move is more company-specific than market-wide."
    return f"{ticker} has modestly outperformed the Nasdaq-100; the wider market still explains part of the move."

def new_listing_snapshot(df, ipo_price=None):
    if df is None or df.empty:
        return {}
    c=df["Close"]
    current=float(c.iloc[-1])
    high=float(c.max())
    low=float(c.min())
    high_date=c.idxmax()
    low_date=c.idxmin()
    out={
        "current":current,
        "high":high,
        "low":low,
        "from_high":(current/high-1)*100 if high else np.nan,
        "from_low":(current/low-1)*100 if low else np.nan,
        "high_date":high_date,
        "low_date":low_date,
        "sessions":len(c),
        "first_date":c.index[0],
    }
    if ipo_price:
        out["ipo_price"]=ipo_price
        out["from_ipo"]=(current/ipo_price-1)*100
    return out

# ---------- CHART ----------
def mobile_chart(df,ticker,entry=None,strategy10=None,strategy20=None):
    data=[]
    for idx,row in df.iterrows():
        data.append({"time":idx.strftime("%Y-%m-%d"),"value":round(float(row["Close"]),4)})
    payload=json.dumps(data)
    markers=[]
    # recent 1y peak and low
    recent=df.tail(252)
    if not recent.empty:
        pdt=recent["Close"].idxmax(); ldt=recent["Close"].idxmin()
        markers=[
            {"time":pdt.strftime("%Y-%m-%d"),"position":"aboveBar","color":"#666","shape":"arrowDown","text":"Recent peak"},
            {"time":ldt.strftime("%Y-%m-%d"),"position":"belowBar","color":"#666","shape":"arrowUp","text":"Recent low"}
        ]
    markers_json=json.dumps(markers)
    price_lines=""
    current=float(df["Close"].iloc[-1])
    recent_peak=float(recent["Close"].max()) if not recent.empty else current
    recent_low=float(recent["Close"].min()) if not recent.empty else current
    price_lines += f"""series.createPriceLine({{price:{current},color:'#555',lineWidth:1,lineStyle:2,axisLabelVisible:true,title:'Current'}});"""
    price_lines += f"""series.createPriceLine({{price:{recent_peak},color:'#777',lineWidth:1,lineStyle:2,axisLabelVisible:true,title:'Recent peak'}});"""
    price_lines += f"""series.createPriceLine({{price:{recent_low},color:'#999',lineWidth:1,lineStyle:2,axisLabelVisible:true,title:'Recent low'}});"""
    if entry:
        price_lines += f"""series.createPriceLine({{price:{float(entry)},color:'#444',lineWidth:2,lineStyle:1,axisLabelVisible:true,title:'My entry'}});"""
    if strategy10:
        price_lines += f"""series.createPriceLine({{price:{float(strategy10)},color:'#777',lineWidth:1,lineStyle:3,axisLabelVisible:true,title:'+10% from today'}});"""
    if strategy20:
        price_lines += f"""series.createPriceLine({{price:{float(strategy20)},color:'#999',lineWidth:1,lineStyle:3,axisLabelVisible:true,title:'+20% from today'}});"""
    chart_html=f"""
    <div style="font-family:Arial,sans-serif">
      <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:8px">
        <button onclick="calendarRange(31)">1M</button><button onclick="calendarRange(92)">3M</button>
        <button onclick="calendarRange(183)">6M</button><button class="active-range" onclick="calendarRange(365)">1Y</button>
        <button onclick="calendarRange(730)">2Y</button><button onclick="calendarRange(1826)">5Y</button>
        <button onclick="fit()">MAX</button>
      </div>
      <div id="readout" style="height:24px;font-size:14px"><b>{ticker}</b></div>
      <div id="chart" style="width:100%;height:430px"></div>
    </div>
    <style>
      button{{border:1px solid #ccc;background:white;border-radius:8px;padding:8px 13px;font-size:14px}}
      button:active{{background:#eee}}
      button.active-range{{background:#eee;font-weight:700}}
    </style>
    <script src="https://unpkg.com/lightweight-charts@4.2.0/dist/lightweight-charts.standalone.production.js"></script>
    <script>
      const data={payload};
      const el=document.getElementById('chart');
      const chart=LightweightCharts.createChart(el,{{
        width:el.clientWidth,height:430,
        layout:{{background:{{color:'#fff'}},textColor:'#333'}},
        grid:{{vertLines:{{color:'#f4f4f4'}},horzLines:{{color:'#f4f4f4'}}}},
        rightPriceScale:{{borderColor:'#ddd'}},
        timeScale:{{borderColor:'#ddd',rightOffset:4,barSpacing:6,minBarSpacing:1.5}},
        crosshair:{{mode:LightweightCharts.CrosshairMode.Normal}},
        handleScroll:{{mouseWheel:true,pressedMouseMove:true,horzTouchDrag:true,vertTouchDrag:false}},
        handleScale:{{axisPressedMouseMove:true,mouseWheel:true,pinch:true}}
      }});
      const series=chart.addLineSeries({{lineWidth:2,priceLineVisible:true}});
      series.setData(data);
      series.setMarkers({markers_json});
      {price_lines}
      function calendarRange(days){{
        if(!data.length)return;
        const last=new Date(data[data.length-1].time+'T00:00:00Z');
        const firstAvailable=new Date(data[0].time+'T00:00:00Z');
        const fromDate=new Date(last);
        fromDate.setUTCDate(fromDate.getUTCDate()-days);
        const effectiveFrom=fromDate<firstAvailable?firstAvailable:fromDate;
        const iso=d=>d.toISOString().slice(0,10);
        chart.timeScale().setVisibleRange({{from:iso(effectiveFrom),to:data[data.length-1].time}});
      }}
      function fit(){{chart.timeScale().fitContent()}}
      chart.subscribeCrosshairMove(p=>{{
        if(!p.time)return;
        const d=p.seriesData.get(series); if(!d)return;
        document.getElementById('readout').innerHTML='<b>{ticker}</b> &nbsp; '+p.time+' &nbsp; $'+d.value.toFixed(2);
      }});
      new ResizeObserver(e=>{{chart.applyOptions({{width:e[0].contentRect.width}})}}).observe(el);
      // Default to a true 365-calendar-day view. Delay until the chart
      // completes its first layout so the initial full-history fit cannot win.
      requestAnimationFrame(()=>requestAnimationFrame(()=>calendarRange(365)));
    </script>
    """
    components.html(chart_html,height=505,scrolling=False)

def analogue_chart(df,matches,ticker):
    if matches.empty:return
    c=df["Close"]
    series=[]
    # current: last 63 days ending today, normalized at first point
    cur=c.tail(63)
    curvals=(cur/cur.iloc[0]*100).tolist()
    series.append({"name":"Current","vals":[round(float(x),2) for x in curvals]})
    for _,r in matches.head(5).iterrows():
        dt=pd.Timestamp(r["Date"])
        try: pos=df.index.get_loc(dt)
        except: continue
        seg=c.iloc[max(0,pos-31):min(len(c),pos+64)]
        if len(seg)<40:continue
        vals=(seg/seg.iloc[0]*100).tolist()
        series.append({"name":str(r["Date"]),"vals":[round(float(x),2) for x in vals]})
    payload=json.dumps(series)
    chart_html=f"""
    <div id="ac" style="width:100%;height:360px"></div>
    <script src="https://unpkg.com/lightweight-charts@4.2.0/dist/lightweight-charts.standalone.production.js"></script>
    <script>
      const sets={payload};
      const el=document.getElementById('ac');
      const chart=LightweightCharts.createChart(el,{{width:el.clientWidth,height:350,
        layout:{{background:{{color:'#fff'}},textColor:'#333'}},
        grid:{{vertLines:{{color:'#f4f4f4'}},horzLines:{{color:'#f4f4f4'}}}},
        rightPriceScale:{{borderColor:'#ddd'}},timeScale:{{visible:false}}}});
      sets.forEach((s,idx)=>{{
        const line=chart.addLineSeries({{lineWidth:idx===0?3:1,lastValueVisible:false,priceLineVisible:false}});
        line.setData(s.vals.map((v,i)=>({{time:i+1,value:v}})));
      }});
      chart.timeScale().fitContent();
      new ResizeObserver(e=>chart.applyOptions({{width:e[0].contentRect.width}})).observe(el);
    </script>
    """
    components.html(chart_html,height=365,scrolling=False)

# ---------- LOAD BENCHMARKS ----------
qqq=load_price("QQQ",10); spy=load_price("SPY",10)
qqq5=(float(qqq["Close"].iloc[-1])/float(qqq["Close"].iloc[-6])-1)*100 if len(qqq)>6 else np.nan
spy5=(float(spy["Close"].iloc[-1])/float(spy["Close"].iloc[-6])-1)*100 if len(spy)>6 else np.nan

# ---------- BUILD STOCK DATA ----------
stocks={}
for t in WATCHLIST:
    df=load_price(t,10)
    # New listings such as SpaceX must not be discarded simply because they
    # do not yet have years of price history. Twenty sessions is enough for
    # the live dip/rebound engine; historical analogue analysis remains empty
    # until sufficient history accumulates.
    if df.empty or len(df)<20:
        continue
    intraday_price,intraday_ts=load_intraday(t)
    if intraday_price is not None:
        df=df.copy()
        df.loc[df.index[-1],"Close"]=intraday_price
        if "High" in df.columns:
            df.loc[df.index[-1],"High"]=max(float(df.loc[df.index[-1],"High"]),intraday_price)
        if "Low" in df.columns:
            df.loc[df.index[-1],"Low"]=min(float(df.loc[df.index[-1],"Low"]),intraday_price)
    f=feature_frame(df)
    matches=historical_matches(df,f)
    info=load_fundamentals(t)
    current=float(df["Close"].iloc[-1])
    fund_label,fund_notes=fundamental_assessment(info,current)
    engine=opportunity_engine(df,f,matches,qqq5,fund_label)
    hs=hist_summary(matches,current)
    stocks[t]={"df":df,"f":f,"matches":matches,"info":info,"fund_label":fund_label,
               "fund_notes":fund_notes,"engine":engine,"hs":hs,"intraday_ts":intraday_ts}

# ---------- SIDEBAR / POSITION TRACKER ----------
st.sidebar.header("My rebound strategy")
stake_gbp=st.sidebar.number_input("Typical amount to deploy (£)",min_value=1000.0,value=20000.0,step=1000.0)
st.sidebar.caption("Core objective: capture roughly 10–20% rebounds after unusually attractive falls.")
st.sidebar.header("My position (optional)")
held=st.sidebar.selectbox("Stock",["None"]+WATCHLIST)
entry_price=st.sidebar.number_input("Entry price ($)",min_value=0.0,value=0.0,step=1.0)
position_value=st.sidebar.number_input("Amount invested",min_value=0.0,value=0.0,step=500.0)
risk_budget=st.sidebar.number_input("Maximum acceptable loss",min_value=0.0,value=0.0,step=100.0)

# ---------- HOME ----------
st.title("🎯 Share Sniper")
st.caption("Find large, established shares with meaningful corrections and target the rebound — without forcing a trade every day.")

# ---------- VISUAL HIERARCHY ----------
# Burgundy is reserved for navigation/section emphasis; green/red remain free for market signals.
st.markdown("""
<style>
:root { --sniper-burgundy: #7A1F3D; --sniper-burgundy-soft: #F7EEF1; }
.sniper-section-heading {
    color: var(--sniper-burgundy);
    font-size: 1.55rem;
    font-weight: 750;
    line-height: 1.2;
    letter-spacing: .01em;
    margin: 2.0rem 0 .9rem 0;
    padding: 0 0 .42rem 0;
    border-bottom: 3px solid var(--sniper-burgundy);
}
.sniper-ticker-heading {
    color: var(--sniper-burgundy);
    font-size: 1.45rem;
    font-weight: 800;
    line-height: 1.2;
    margin: .15rem 0 .65rem 0;
}
/* Make stock tabs obvious and easy to spot/tap while scrolling on mobile. */
.stTabs [data-baseweb=\"tab-list\"] { gap: .35rem; margin-top: .25rem; margin-bottom: .8rem; }
.stTabs [data-baseweb=\"tab\"] {
    height: 3rem;
    padding: 0 .95rem;
    font-size: 1.05rem;
    font-weight: 750;
    color: #303030;
    border-radius: .55rem .55rem 0 0;
}
.stTabs [aria-selected=\"true\"] {
    color: var(--sniper-burgundy) !important;
    background: var(--sniper-burgundy-soft) !important;
}
.stTabs [data-baseweb=\"tab-highlight\"] { background-color: var(--sniper-burgundy) !important; height: 3px; }
@media (max-width: 640px) {
    .sniper-section-heading { font-size: 1.38rem; margin-top: 1.65rem; }
    .sniper-ticker-heading { font-size: 1.32rem; }
    .stTabs [data-baseweb=\"tab\"] { font-size: 1rem; padding: 0 .72rem; min-width: 3.7rem; }
}
</style>
""", unsafe_allow_html=True)

market_state, now_ny = us_market_status()
now_uk = datetime.now(ZoneInfo("Europe/London"))
latest_times=[x.get("intraday_ts") for x in stocks.values() if x.get("intraday_ts") is not None]
if latest_times:
    try:
        freshest=max(latest_times)
        fresh_text=freshest.strftime("%d %b %Y, %H:%M ET")
    except Exception:
        fresh_text=now_ny.strftime("%d %b %Y, %H:%M ET")
else:
    fresh_text=now_ny.strftime("%d %b %Y, %H:%M ET")

st.write(
    f"Prices last refreshed: {now_uk.strftime('%d %b %Y, %H:%M UK time')} · "
    f"Latest market-data point: {fresh_text} · US regular market: {market_state}"
)
st.caption("The page refreshes automatically every 5 minutes. Intraday prices use 5-minute Yahoo/yfinance data when available; they may be delayed. US market status is based on normal weekday trading hours and does not account for every exchange holiday.")
st.info(f"CORE STRATEGY: Deploy about £{stake_gbp:,.0f} into an unusually attractive dip in a large, established company. Aim to capture at least +10% (about £{stake_gbp*.10:,.0f} gross), with +20% (about £{stake_gbp*.20:,.0f} gross) as the preferred rebound objective.")

if stocks:
    ranked=sorted(stocks.items(), key=lambda kv: rebound_strategy_snapshot(kv[1]["df"],kv[1]["matches"],stake_gbp)["score"], reverse=True)
    st.markdown('<div class="sniper-section-heading">Today\'s Sniper Opportunities</div>', unsafe_allow_html=True)
    st.caption("Start here. Shares are ranked by how attractive the current buying price looks for our 10–20% rebound strategy. Core wave shares and occasional deep-dip shares are both included; a high rank is a prompt to investigate, not an instruction to buy.")
    daily=[]
    for t,x in ranked:
        snap=rebound_strategy_snapshot(x["df"],x["matches"],stake_gbp)
        daily.append((t,x,snap))
    strong=[row for row in daily if row[2]["entry_score"] >= 63]
    if not strong:
        st.info("NO COMPELLING ENTRY TODAY — none of the shares currently clears the stronger buying-opportunity threshold. Waiting is a valid result.")
    for pos,(t,x,snap) in enumerate(daily[:5], start=1):
        price=float(x["df"]["Close"].iloc[-1])
        company=COMPANY_NAMES.get(t,t)
        with st.container(border=True):
            st.markdown(f"### #{pos} · {company} ({t}) · {display_price(t,price)}")
            st.write(f"Buying opportunity today: {snap['entry_score']}/100 — {snap['verdict']}.")
            st.caption(SNIPER_PROFILES.get(t,""))
            st.write(snap["entry_explain"])
            st.write(f"£{stake_gbp:,.0f} objective: +10% ≈ £{snap['gain10']:,.0f} gross · +20% ≈ £{snap['gain20']:,.0f} gross.")

    st.markdown('<div class="sniper-section-heading">Opportunity board</div>', unsafe_allow_html=True)
    for t,x in ranked:
        df=x["df"]; f=x["f"]; matches=x["matches"]; e=x["engine"]; hs=x["hs"]; cur=f.iloc[-1]; price=float(df["Close"].iloc[-1])
        with st.container(border=True):
            snap=rebound_strategy_snapshot(df,matches,stake_gbp)
            label, meaning, instinct = score_explanation(snap["entry_score"])
            st.markdown(f'<div class="sniper-ticker-heading">{t} · {display_price(t,price)}</div>', unsafe_allow_html=True)
            if cur["3M_DD"] <= -12 and cur["5D"] > 2:
                plain_state = "SHARE PRICE MAY BE STARTING TO RISE AGAIN"
            elif cur["5D"] <= -5:
                plain_state = "SHARE PRICE IS STILL FALLING"
            elif cur["3M_DD"] <= -12:
                plain_state = "SHARE PRICE REMAINS WELL BELOW ITS RECENT HIGH"
            else:
                plain_state = "NO MAJOR BUYING OPPORTUNITY DETECTED"
            st.markdown(f"**{plain_state}**")
            st.caption(SNIPER_PROFILES.get(t,""))
            st.write(f"Buying opportunity today: {snap['entry_score']}/100 — {snap['verdict']}.")
            st.write(f"Size of recent dip: {snap['dip_quality']}/100. {snap['summary']}")
            st.write(snap["entry_explain"])
            st.write(f"Today: {cur['1D']:+.1f}% · Last 5 trading days: {cur['5D']:+.1f}% · Last month: {cur['1M']:+.1f}% · From 3-month high: {cur['3M_DD']:.1f}%")
            if hs:
                n = hs["n"]
                up3 = int((matches["3M %"] > 0).sum())
                valid3 = int(matches["3M %"].notna().sum())
                st.write(f"History: Tesla's share price was higher 3 months later in {up3} of {valid3} similar situations." if t=="TSLA" else f"History: {t}'s share price was higher 3 months later in {up3} of {valid3} similar situations.")
            st.write("What this means for you: WAIT — SEE IF THE PRICE FALLS FURTHER." if 48 <= snap["entry_score"] < 63 else f"What this means for you: {snap['instinct']}.")
            st.write(f"£{stake_gbp:,.0f} rebound view: +10% = about £{snap['gain10']:,.0f} gross; +20% = about £{snap['gain20']:,.0f} gross.")
            st.write(f"Strategy verdict: {snap['verdict']} · {snap['summary']}")

st.divider()
st.markdown('<div class="sniper-section-heading">Deep analysis</div>', unsafe_allow_html=True)
tabs=st.tabs(WATCHLIST)

for tab,t in zip(tabs,WATCHLIST):
    if t not in stocks:continue
    x=stocks[t]
    with tab:
        df=x["df"]; f=x["f"]; matches=x["matches"]; info=x["info"]; e=x["engine"]; hs=x["hs"]
        snap=rebound_strategy_snapshot(df,matches,stake_gbp)
        cur=f.iloc[-1]; price=float(df["Close"].iloc[-1])

        snap=rebound_strategy_snapshot(df,matches,stake_gbp)
        st.markdown(f'<div class="sniper-ticker-heading">{COMPANY_NAMES.get(t,t)} ({t}) — {display_price(t,price)}</div>', unsafe_allow_html=True)

        st.markdown("### Main price chart")
        st.caption("Pinch to zoom and swipe to pan. The +10% and +20% lines are your rebound objectives from today’s price — not analyst forecasts.")
        entry_for_chart=entry_price if held==t and entry_price>0 else None
        strategy_snap=rebound_strategy_snapshot(df,matches,stake_gbp)
        mobile_chart(df,t,entry_for_chart,strategy_snap["target10"],strategy_snap["target20"])

        if cur["3M_DD"] <= -12 and cur["5D"] > 2:
            plain_state = "SHARE PRICE MAY BE STARTING TO RISE AGAIN"
            plain_explain = f"{t} is still {abs(cur['3M_DD']):.1f}% below its 3-month high, but its share price has risen {cur['5D']:.1f}% over the last 5 trading days. That may be an early sign that the recent fall is ending and the share price is beginning to move higher again."
        elif cur["5D"] <= -5:
            plain_state = "SHARE PRICE IS STILL FALLING"
            plain_explain = f"{t}'s share price has fallen {abs(cur['5D']):.1f}% over the last 5 trading days. The lower price may eventually create an opportunity, but there is not yet clear evidence that the fall has stopped."
        elif cur["3M_DD"] <= -12:
            plain_state = "SHARE PRICE REMAINS DEPRESSED"
            plain_explain = f"{t} remains {abs(cur['3M_DD']):.1f}% below its 3-month high. The price is cheaper than at its recent peak, but there is not yet a strong upward move confirming a recovery."
        else:
            plain_state = "NO MAJOR PRICE OPPORTUNITY DETECTED"
            plain_explain = "The current price pattern does not show the combination of a major fall and an emerging recovery that this tool is designed to find."
        st.markdown(f"### {plain_state}")
        st.write(plain_explain)
        st.info("Sniper profile: " + SNIPER_PROFILES.get(t,"This share is monitored for meaningful dip-and-rebound opportunities."))

        if t=="SPCX":
            spx=new_listing_snapshot(df,135.0)
            if spx:
                st.markdown("### SpaceX analysis summary")
                c1,c2,c3,c4=st.columns(4)
                c1.metric("Current price",display_price(t,spx["current"]))
                c2.metric("Since $135 IPO",f'{spx["from_ipo"]:+.1f}%')
                c3.metric("From public-market high",f'{spx["from_high"]:+.1f}%')
                c4.metric("Rebound from public-market low",f'{spx["from_low"]:+.1f}%')
                st.write(
                    f"SpaceX has only {spx['sessions']} trading sessions of public history, so the app uses its entire "
                    f"post-IPO trading range as the medium-term reference rather than pretending it has 3, 6 or 12 months of history. "
                    f"Its public-market high is {display_price(t,spx['high'])} and its public-market low is {display_price(t,spx['low'])}."
                )
                st.write(
                    "What matters today: the app gives SpaceX the same Buying Opportunity Today score, RSI, recent-price analysis, "
                    "market-relative comparison, £20,000 rebound targets, chart, fundamentals and news review as every other share. "
                    "The only part that is deliberately unavailable is the multi-year historical-analogue evidence, because that history does not yet exist."
                )

        st.markdown(f"### Buying opportunity today: {snap['entry_score']}/100 — {snap['verdict']}")
        st.write(snap["summary"])
        st.write(snap["entry_explain"])
        st.write(f"Your instinct: {snap['instinct']}.")
        if t=="QCOM":
            if price <= 155:
                st.success("QUALCOMM DEEP-DIP AREA: the price is in/near the $140–$150 area we identified as especially worth investigating. This is still not an automatic buy.")
            elif price <= 165:
                st.info("QUALCOMM WATCH AREA: getting closer to the deep-dip zone. A cheaper price around $140–$150 would be more interesting for this strategy.")
            else:
                st.caption("Qualcomm is an occasional deep-dip share for us. We are more interested after a much larger fall, especially around the $140–$150 area.")
        if t=="SPCX":
            st.warning("SPACEX — FULL SNIPER TREATMENT: SpaceX is scored and analysed like every other share. The app only omits the multi-year analogue statistics that cannot yet exist. Short public history is a limitation on historical evidence, not a reason to suppress the opportunity analysis.")
            ipo_price=135.0
            ipo_move=(price/ipo_price-1)*100
            st.write(f"IPO reference: $135.00 · current price is {ipo_move:+.1f}% versus the IPO price.")
            st.write("Extra SpaceX intelligence: post-IPO high/low and rebound size, share-unlock/lock-up supply pressure, results, Starlink/launch execution, AI/compute investment, financing/capital expenditure, valuation and whether today's move is company-specific or part of the wider growth/tech market.")
        if t=="BA":
            st.warning("BOEING SPECIAL RULE: a large fall can create opportunity, but Boeing has more company-specific operational/regulatory risk than the other names. Check the reason for any collapse before considering an entry.")
        if t=="AVGO":
            st.warning("BROADCOM SPECIAL RULE: false bottoms can occur. Prefer stronger evidence that the fall has stabilised before treating a large drop as an entry.")
        d1,d2=st.columns(2)
        d1.metric("Size of recent dip",f"{snap['dip_quality']}/100")
        d2.metric("Buying opportunity today",f"{snap['entry_score']}/100")
        st.caption("Size of recent dip asks: 'Has this stock suffered a major fall?' Buying opportunity today asks the more important question: 'Is today's actual price attractive enough to put money in now?'")
        a,b,c=st.columns(3)
        a.metric("Share price",f"${price:,.2f}",f"{cur['1D']:+.1f}% today")
        b.metric("Below 3M high",f"{cur['3M_DD']:.1f}%")
        c.metric("RSI",f"{cur['RSI']:.0f}")

        st.markdown("### Market or company-specific move?")
        market_rows=market_move_summary(df,qqq,spy)
        st.write("Nasdaq-100 (QQQ) = a broad measure of large US technology and growth companies.")
        st.write("S&P 500 (SPY) = a broad measure of the largest US companies overall.")
        display_market = market_rows.rename(columns={"Stock":t})
        st.dataframe(
            display_market.style.format({
                t:"{:+.1f}%",
                "Nasdaq-100 (QQQ)":"{:+.1f}%",
                "S&P 500 (SPY)":"{:+.1f}%",
                "vs Nasdaq":"{:+.1f} pts"
            }),
            hide_index=True,
            use_container_width=True
        )
        st.info(market_move_interpretation(market_rows,t))

        st.markdown("### Why the app thinks this")
        st.write(e["narrative"])
        if e["reasons"]:
            st.write("Why the score is where it is: " + "; ".join(e["reasons"]) + ".")
        if e["cautions"]:
            st.warning("Cautions: " + "; ".join(e["cautions"]) + ".")

        st.markdown("### Your £20k-style rebound setup")
        snap=rebound_strategy_snapshot(df,matches,stake_gbp)
        st.markdown(f"#### {snap['verdict']} — buying opportunity {snap['entry_score']}/100")
        st.write(f"The question here is simple: does today's price look like a good place to deploy about £{stake_gbp:,.0f} if the goal is to capture the next 10–20% rebound?")
        s1,s2,s3=st.columns(3)
        s1.metric("Today's share price",f"${price:,.2f}")
        s2.metric("+10% share price",f"${snap['target10']:,.2f}",f"≈ £{snap['gain10']:,.0f} gross")
        s3.metric("+20% share price",f"${snap['target20']:,.2f}",f"≈ £{snap['gain20']:,.0f} gross")
        st.write(snap["peak_context"])

        if snap["n"] >= 5:
            st.markdown("#### What happened in comparable historical situations?")
            if pd.notna(snap["p10"]):
                d10txt=f" The typical successful case took about {snap['days10']:.0f} trading days." if pd.notna(snap["days10"]) else ""
                st.write(f"In {snap['hit10']} of {snap['n']} comparable situations with a full year of later price history, the share subsequently rose at least 10% above the comparison price.{d10txt}")
            if pd.notna(snap["p20"]):
                d20txt=f" The typical successful case took about {snap['days20']:.0f} trading days." if pd.notna(snap["days20"]) else ""
                st.write(f"In {snap['hit20']} of {snap['n']} comparable situations, the share subsequently rose at least 20% above the comparison price.{d20txt}")
            if pd.notna(snap["meddown"]):
                st.write(f"But before/during those later outcomes, the typical lowest price in completed 6-month comparisons was another {abs(snap['meddown']):.1f}% below the historical comparison price.")
        else:
            st.write("There are not yet enough completed one-year historical comparisons to give a reliable 10%/20% success rate.")

        st.info("What this means for your strategy: " + snap["summary"] + " The app treats the further-downside history as important because a later 20% rebound is much less useful if the share commonly falls much further first.")

        st.markdown("### Price behaviour — in plain English")
        moves=period_rows(df,f)
        st.dataframe(moves.style.format({
            "Was":"${:,.2f}","Now":"${:,.2f}","Move":"${:+,.2f}",
            "Change %":"{:+.1f}%","Tail percentile":"{:.1f}%"
        }),hide_index=True,use_container_width=True)
        st.caption("Tail percentile asks how unusual the move is versus this stock's own history. A very low figure on a decline means unusually severe weakness.")

        # RSI translated for the dip-buying strategy
        rsi5=float(f["RSI"].iloc[-6]) if len(f)>=6 and pd.notna(f["RSI"].iloc[-6]) else np.nan
        rsi_label,rsi_meaning=rsi_explanation(float(cur["RSI"]),rsi5)
        st.markdown("### RSI — what it means for this strategy")
        r1,r2=st.columns(2)
        r1.metric("Today's RSI",f"{cur['RSI']:.0f}/100",rsi_label)
        r2.metric("Ideal area to watch","20–35")
        st.write("RSI measures how strongly the share price has recently been rising or falling. For this dip-buying strategy, lower readings are generally more interesting — but the best signal is often a low RSI that then starts rising while the share price also starts rising.")
        st.write(f"What today's reading means: {rsi_meaning}")
        st.caption("Below 30 is traditionally called oversold; above 70 is traditionally called overbought. RSI alone is never treated as a buy signal.")

        st.markdown("### Historical opportunity engine")
        if hs:
            h1,h2,h3,h4=st.columns(4)
            h1.metric("Similar episodes",hs["n"])
            completed1y_metric = matches[matches["Full 1Y history"]==True] if "Full 1Y history" in matches.columns else matches.iloc[0:0]
            h2.metric("Later rose 20%+",f"{int(completed1y_metric['Days +20%'].notna().sum())} of {len(completed1y_metric)}" if len(completed1y_metric) else "Not enough history")
            h3.metric("Typical 6M return",f"{hs['med6']:+.1f}%" if pd.notna(hs["med6"]) else "Not enough history")
            h4.metric("Typical further fall",f"{abs(hs['meddown']):.1f}%" if pd.notna(hs["meddown"]) else "Not enough history")
            valid1 = matches["1M %"].dropna()
            valid3 = matches["3M %"].dropna()
            valid6 = matches["6M %"].dropna()
            up1 = int((valid1 > 0).sum())
            up3 = int((valid3 > 0).sum())
            up6 = int((valid6 > 0).sum())
            st.write(f"We found {hs['n']} previous situations in {t}'s price history that most closely resemble what is happening now.")
            if len(valid1):
                st.write(f"• 1 month later, the share price was higher in {up1} of {len(valid1)} comparable situations. The typical return was {hs['med1']:+.1f}%.")
            if len(valid3):
                st.write(f"• 3 months later, the share price was higher in {up3} of {len(valid3)} comparable situations. The typical return was {hs['med3']:+.1f}%.")
            if len(valid6):
                st.write(f"• 6 months later, the share price was higher in {up6} of {len(valid6)} comparable situations. The typical return was {hs['med6']:+.1f}%.")
            completed1y = matches[matches["Full 1Y history"]==True] if "Full 1Y history" in matches.columns else matches.iloc[0:0]
            hit20 = int(completed1y["Days +20%"].notna().sum()) if len(completed1y) else 0
            if len(completed1y):
                st.write(f"• In {hit20} of the {len(completed1y)} comparable situations with a full year of later price history, the share price at some point rose at least 20% above the historical comparison price. This does not mean an investor necessarily made 20%, because the price may have fallen substantially first.")
            else:
                st.write("• There are not enough comparable situations with a full year of later price history to give a reliable '+20%' count.")
            if pd.notna(hs["meddown"]):
                st.write(f"• Looking only at cases with a full 6 months of later price history, the typical lowest point afterwards was another {abs(hs['meddown']):.1f}% below the comparison price.")
            if pd.notna(hs["med6"]) and hs["med6"] > 0:
                conclusion = "Historically, buying at a similar stage often worked reasonably well, although further falls were still possible."
            else:
                conclusion = "Historically, this exact stage was often too early to buy: the share frequently fell further and the typical 6-month return was still negative."
            st.info("What this means: " + conclusion)
            with st.expander("Show the individual historical examples"):
                display_matches = matches.drop(columns=["Similarity","Low proximity %"], errors="ignore")
                st.dataframe(display_matches.style.format({
                    "1M %":"{:+.1f}%","3M %":"{:+.1f}%","6M %":"{:+.1f}%",
                    "Best 6M %":"{:+.1f}%","Further downside %":"{:+.1f}%"
                }),hide_index=True,use_container_width=True)

            with st.expander("Show visual comparison with similar historical falls"):
                st.write("Each line shows how the share price moved around one of the most similar historical situations. The lines are rebased to the same starting value so their shapes can be compared; they are not actual share prices.")
                analogue_chart(df,matches,t)

        st.markdown("### Price levels & possible opportunity")
        peak3,low3=recent_levels(df,63)
        peak_up=(peak3/price-1)*100
        low_from=(price/low3-1)*100
        p1,p2,p3=st.columns(3)
        p1.metric("Current share price",f"${price:,.2f}")
        p2.metric("Recent 3M high",f"${peak3:,.2f}",f"{peak_up:+.1f}% needed to get back there")
        p3.metric("Recent 3M low",f"${low3:,.2f}",f"current price is {low_from:+.1f}% above it")
        st.caption("These three prices are factual market levels, not forecasts.")

        lower,upper,zone_note=entry_zone(df,f,matches)
        st.markdown("#### Potential entry area")
        if pd.notna(lower) and pd.notna(upper):
            st.write(f"${lower:,.2f}–${upper:,.2f}")
            st.write(zone_note)
        else:
            st.write("No attractive dip-entry area identified right now.")
            st.write(zone_note)

        st.markdown("#### Historical recovery estimate")
        if hs and pd.notna(hs.get("target_pct",np.nan)):
            st.write(f"If the typical 6-month outcome from the completed similar historical situations repeated, the share price would be about ${hs['target']:,.2f} — approximately {hs['target_pct']:+.1f}% from today's price.")
            st.caption(f"This is calculated by this app from {hs['n6']} completed historical 6-month comparisons. It is not an analyst forecast or a Yahoo Finance price target.")
        else:
            completed = hs.get("n6",0) if hs else 0
            st.write(f"No meaningful positive historical recovery estimate is shown. There are {completed} completed 6-month comparisons, and/or their typical outcome does not support a positive estimate.")
            st.caption("The app deliberately does not turn the current price into a meaningless 'target' when historical evidence is weak.")

        st.markdown("#### Analyst consensus — separate from our historical estimate")
        analyst_target=info.get("targetMeanPrice")
        analyst_n=info.get("numberOfAnalystOpinions")
        if isinstance(analyst_target,(int,float)) and analyst_target>0:
            analyst_up=(analyst_target/price-1)*100
            st.write(f"Analyst mean price target: ${analyst_target:,.2f} ({analyst_up:+.1f}% versus today's price)"
                     + (f", based on {analyst_n} analyst opinions." if isinstance(analyst_n,(int,float)) and analyst_n>0 else "."))
            st.caption("This is external analyst-consensus data returned by yfinance/Yahoo Finance data, not a target calculated by this app.")
        else:
            st.write("Analyst consensus target is not currently available from the data feed.")
        st.markdown("### Fundamentals & valuation snapshot")

        st.markdown("### Fundamentals & valuation snapshot")
        st.write(f"Fundamental health: {x['fund_label']}.")
        if x["fund_notes"]: st.write(" · ".join(x["fund_notes"]) + ".")
        fund_rows=[]
        labels=[
            ("Forward P/E","forwardPE","x"),("Trailing P/E","trailingPE","x"),
            ("Revenue growth","revenueGrowth","pct"),("Earnings growth","earningsGrowth","pct"),
            ("Profit margin","profitMargins","pct"),("Analyst mean target","targetMeanPrice","money"),
            ("Analyst opinions","numberOfAnalystOpinions","num")
        ]
        for label,key,kind in labels:
            v=info.get(key)
            if v is None:continue
            if kind=="pct": disp=f"{v*100:.1f}%"
            elif kind=="money": disp=f"${v:,.2f}"
            elif kind=="x": disp=f"{v:.1f}x"
            else: disp=str(v)
            fund_rows.append({"Metric":label,"Value":disp})
        if fund_rows:st.dataframe(pd.DataFrame(fund_rows),hide_index=True,use_container_width=True)
        st.caption("Fundamental data availability varies by company and data provider. This snapshot is deliberately secondary to the price/history analysis.")

        st.markdown("### Why is it moving? — recent catalyst scan")
        news=load_news(t)
        cats=classify_news(news)
        st.write("Current headline themes: " + ", ".join(cats) + ".")
        if news:
            for n in news[:5]:
                title=n["title"]
                pub=f" — {n['publisher']}" if n.get("publisher") else ""
                if n.get("url"):
                    st.markdown(f"- [{title}]({n['url']}){pub}")
                else:
                    st.write(f"• {title}{pub}")
        else:
            st.write("No recent headline feed was available from the current market-data source.")
        st.caption("Headline classification is a screening aid. The app does not assume that a headline proves the cause of a price move.")

        if held==t and entry_price>0:
            st.markdown("### My trade")
            ret=(price/entry_price-1)*100
            pnl=position_value*ret/100 if position_value>0 else 0
            if hs and pd.notna(hs.get("target",np.nan)) and price>=hs["target"]*0.95: lifecycle="HISTORICAL RECOVERY AREA"
            elif ret>=10:lifecycle="RECOVERY / REVIEW"
            elif ret>=0:lifecycle="RECOVERY DEVELOPING"
            elif e["status"]=="DEEP SELLOFF":lifecycle="RISK REVIEW"
            else:lifecycle="ENTRY / WATCH"
            st.write(f"Lifecycle: {lifecycle}")
            st.write(f"Entry ${entry_price:,.2f} → current ${price:,.2f} · return {ret:+.1f}%"
                     + (f" · estimated P/L {pnl:+,.2f}" if position_value>0 else ""))
            if hs and pd.notna(hs.get("target_pct",np.nan)) and hs["target_pct"]>0:
                expected_total=hs["target"]-entry_price
                achieved=price-entry_price
                pct_done=(achieved/expected_total*100) if expected_total>0 else np.nan
                if pct_done==pct_done:
                    st.write(f"Approximately {pct_done:.0f}% of the move from your entry to the current historical recovery estimate has occurred.")

            if risk_budget>0 and hs and pd.notna(hs.get("meddown",np.nan)) and hs["meddown"]<0:
                risk_per_dollar=abs(hs["meddown"])/100
                max_position=risk_budget/risk_per_dollar
                st.write(f"Position-sizing reference: with a {risk_budget:,.0f} maximum loss and historical median adverse move of {abs(hs['meddown']):.1f}%, the corresponding position size would be about {max_position:,.0f}. This is a risk-budget calculation, not a recommendation.")

st.divider()
st.caption("Decision-support only. Historical analogues, analyst targets and technical indicators are not predictions. Review the underlying news and company fundamentals before trading.")

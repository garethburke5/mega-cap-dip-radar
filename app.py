
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

CORE_WATCHLIST = ["TSLA","NVDA","META","AMZN","GOOGL","AVGO","BARC.L","QCOM","BA","SPCX"]
ROCK_BOTTOM_TICKERS = ["ARM","MSTR","RKLB","SOFI","PLTR"]
ANALYSIS_UNIVERSE = CORE_WATCHLIST + ROCK_BOTTOM_TICKERS
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
    "SOFI":"SoFi Technologies",
    "PLTR":"Palantir Technologies",
    "ARM":"Arm Holdings",
    "MSTR":"Strategy (MicroStrategy)",
    "RKLB":"Rocket Lab",
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
    "ARM":"Rock-bottom candidate — fully analyse and chart it, but price discipline matters. Actionable at $140 or below; preferred zone $120–$140.",
    "MSTR":"Rock-bottom / high-risk candidate — fully analyse and chart it, but it is Bitcoin-dependent. Preferred zone $80–$90.",
    "RKLB":"Rock-bottom / higher-risk space candidate — fully analyse and chart it despite not being a mega-cap. Preferred zone $38–$45.",
    "SOFI":"Rock-bottom / higher-volatility fintech candidate — fully analyse and chart it. Preferred zone $13–$15.",
    "PLTR":"Rock-bottom / valuation-sensitive AI candidate — fully analyse and chart it. Preferred zone $100–$120.",
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
        <button onclick="rng(22)">1M</button><button onclick="rng(66)">3M</button>
        <button onclick="rng(132)">6M</button><button onclick="rng(264)">1Y</button>
        <button onclick="rng(528)">2Y</button><button onclick="rng(1320)">5Y</button>
        <button onclick="fit()">MAX</button>
      </div>
      <div id="readout" style="height:24px;font-size:14px"><b>{ticker}</b></div>
      <div id="chart" style="width:100%;height:430px"></div>
    </div>
    <style>
      button{{border:1px solid #ccc;background:white;border-radius:8px;padding:8px 13px;font-size:14px}}
      button:active{{background:#eee}}
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
      function rng(n){{const L=data.length;chart.timeScale().setVisibleLogicalRange({{from:Math.max(0,L-n)-1,to:L+2}})}}
      function fit(){{chart.timeScale().fitContent()}}
      chart.subscribeCrosshairMove(p=>{{
        if(!p.time)return;
        const d=p.seriesData.get(series); if(!d)return;
        document.getElementById('readout').innerHTML='<b>{ticker}</b> &nbsp; '+p.time+' &nbsp; $'+d.value.toFixed(2);
      }});
      new ResizeObserver(e=>{{chart.applyOptions({{width:e[0].contentRect.width}})}}).observe(el);
      rng(132);
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
for t in ANALYSIS_UNIVERSE:
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
held=st.sidebar.selectbox("Stock",["None"]+ANALYSIS_UNIVERSE)
entry_price=st.sidebar.number_input("Entry price ($)",min_value=0.0,value=0.0,step=1.0)
position_value=st.sidebar.number_input("Amount invested",min_value=0.0,value=0.0,step=500.0)
risk_budget=st.sidebar.number_input("Maximum acceptable loss",min_value=0.0,value=0.0,step=100.0)



# ---------- SNIPER TARGETS + TRAFFIC LIGHTS ----------
# Manually agreed Sniper zones where we have explicitly discussed them.
CORE_MANUAL_TARGETS = {
    "TSLA": (300.0, 310.0),
    "META": (520.0, 540.0),
    "QCOM": (140.0, 150.0),
    "BA": (150.0, 170.0),
    "SPCX": (110.0, 120.0),
}

def derived_core_target_zone(df):
    """
    For core shares without an explicitly agreed target, use the lower part of
    the stock's OWN trailing-1Y daily-close distribution. This avoids the old
    mistake of calling a share cheap merely because it is far below a spike.
    """
    if df is None or df.empty:
        return None
    c=df["Close"].dropna().tail(252)
    if len(c)<20:
        c=df["Close"].dropna()
    if c.empty:
        return None
    lo=float(c.quantile(0.10))
    hi=float(c.quantile(0.20))
    if lo>hi: lo,hi=hi,lo
    return lo,hi

def sniper_target_zone(ticker, df=None):
    if ticker in ROCK_BOTTOM:
        cfg=ROCK_BOTTOM[ticker]
        return float(cfg["entry_low"]), float(cfg["entry_high"])
    if ticker in CORE_MANUAL_TARGETS:
        return CORE_MANUAL_TARGETS[ticker]
    return derived_core_target_zone(df)

def target_label(ticker, zone):
    if not zone:
        return ""
    lo,hi=zone
    if ticker.endswith(".L"):
        return f"{lo:,.0f}–{hi:,.0f}p"
    return f"${lo:,.0f}–${hi:,.0f}"

def all_share_signal(ticker, price, df=None):
    """
    Price comes FIRST.
    GREEN only when the live price has actually reached the Sniper target zone.
    AMBER means close enough to watch carefully (within ~8% above the zone).
    RED means price still needs a more meaningful fall.
    """
    zone=sniper_target_zone(ticker,df)
    if not zone:
        return "RED","WAIT","#B42318","#FDECEC",zone
    lo,hi=zone
    if price <= hi:
        return "GREEN","CHECK FUNDAMENTALS","#198754","#EAF7EF",zone
    if price <= hi*1.08:
        return "AMBER","APPROACHING","#B26A00","#FFF4D6",zone
    return "RED","WAIT — PRICE TOO HIGH","#B42318","#FDECEC",zone

def sniper_badge(signal,label,colour,bg):
    return (
        f'<span style="display:inline-block;padding:4px 9px;border-radius:999px;'
        f'font-weight:800;color:{colour};background:{bg};border:1px solid {colour};'
        f'font-size:0.86rem;">{signal} · {label}</span>'
    )

# ---------- ROCK-BOTTOM WATCHLIST ----------
ROCK_BOTTOM = {
    "ARM": {
        "name": "Arm Holdings",
        "watch_below": 160.0,
        "entry_low": 120.0,
        "entry_high": 140.0,
        "action_price": 140.0,
        "comment": "Only interesting near its old lower trading base; a fall from a recent spike alone does not make it cheap."
    },
    "MSTR": {
        "name": "Strategy (MicroStrategy)",
        "watch_below": 130.0,
        "entry_low": 80.0,
        "entry_high": 90.0,
        "action_price": 90.0,
        "comment": "High-risk, Bitcoin-dependent rebound trade. Check Bitcoin and Strategy-specific news before acting."
    },
    "RKLB": {
        "name": "Rocket Lab",
        "watch_below": 50.0,
        "entry_low": 38.0,
        "entry_high": 45.0,
        "action_price": 45.0,
        "comment": "Higher-risk space special situation, not a mega-cap. Only consider at a deep discount; check Neutron, launch and company-specific news before acting."
    },
    "SOFI": {
        "name": "SoFi Technologies",
        "watch_below": 16.0,
        "entry_low": 13.0,
        "entry_high": 15.0,
        "action_price": 15.0,
        "comment": "Higher-volatility fintech, not a mega-cap. Keep it fully graphed and analysed, but only consider buying at a genuinely depressed price."
    },
    "PLTR": {
        "name": "Palantir Technologies",
        "watch_below": 140.0,
        "entry_low": 100.0,
        "entry_high": 120.0,
        "action_price": 120.0,
        "comment": "Strong AI/data business with valuation risk. Keep it fully graphed and analysed; only consider buying after a major price reset."
    },
}

def rock_bottom_signal(price, cfg):
    if price <= cfg["entry_high"]:
        return "GREEN", "CHECK FUNDAMENTALS", "#198754", "#EAF7EF"
    if price <= cfg["watch_below"]:
        return "AMBER", "APPROACHING", "#B26A00", "#FFF4D6"
    return "RED", "NOWHERE NEAR TARGET", "#B42318", "#FDECEC"

def rock_bottom_snapshot(ticker, cfg):
    df = load_price(ticker, 1)
    if df.empty: return None
    intraday_price, _ = load_intraday(ticker)
    price = float(intraday_price) if intraday_price is not None else float(df["Close"].iloc[-1])
    c = df["Close"].astype(float)
    chg5 = (price/float(c.iloc[-6])-1)*100 if len(c)>=6 else 0.0
    chg20 = (price/float(c.iloc[-21])-1)*100 if len(c)>=21 else chg5
    if chg5 <= -3: direction = "FALLING TOWARD TARGET"
    elif chg5 >= 3: direction = "MOVING AWAY / REBOUNDING"
    elif chg20 <= -5: direction = "DRIFTING LOWER"
    elif chg20 >= 5: direction = "TRENDING HIGHER"
    else: direction = "SIDEWAYS / STABILISING"
    if cfg["entry_low"] <= price <= cfg["entry_high"]: status = "AT SNIPER ENTRY ZONE"
    elif price < cfg["entry_low"]: status = "BELOW ENTRY ZONE — INVESTIGATE WHY"
    elif price <= cfg["watch_below"]: status = "WATCH CLOSELY"
    else: status = "IGNORE FOR NOW"
    distance=(price/cfg["action_price"]-1)*100
    signal, signal_text, signal_colour, signal_bg = rock_bottom_signal(price, cfg)
    return {"ticker":ticker,"name":cfg["name"],"price":price,"direction":direction,
            "status":status,"distance":distance,"cfg":cfg,
            "signal":signal,"signal_text":signal_text,"signal_colour":signal_colour,"signal_bg":signal_bg}

rock_bottom_rows=[]
for _ticker,_cfg in ROCK_BOTTOM.items():
    _rb=rock_bottom_snapshot(_ticker,_cfg)
    if _rb: rock_bottom_rows.append(_rb)


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
st.caption(f"Strategy: deploy about £{stake_gbp:,.0f} only when the price is genuinely attractive; target roughly +10% to +20% rebound.")


if stocks:
    ranked = []
    for t in CORE_WATCHLIST:
        if t not in stocks:
            continue
        x = stocks[t]
        price = float(x["df"]["Close"].iloc[-1])
        snap = rebound_strategy_snapshot(x["df"], x["matches"], stake_gbp)
        sig, sig_label, sig_colour, sig_bg, zone = all_share_signal(t, price, x["df"])
        target = target_label(t, zone)
        rank_order = {"GREEN": 0, "AMBER": 1, "RED": 2}.get(sig, 3)
        zone_hi = zone[1] if zone else None
        distance = ((price / zone_hi) - 1) * 100 if zone_hi else None
        ranked.append({
            "ticker": t,
            "company": COMPANY_NAMES.get(t, t),
            "price": price,
            "signal": sig,
            "signal_label": sig_label,
            "signal_colour": sig_colour,
            "signal_bg": sig_bg,
            "target": target,
            "distance": distance,
            "entry_score": snap["entry_score"],
            "verdict": snap["verdict"],
        })

    ranked = sorted(
        ranked,
        key=lambda r: ({"GREEN": 0, "AMBER": 1, "RED": 2}.get(r["signal"], 3),
                       abs(r["distance"]) if r["distance"] is not None else 999)
    )

    st.markdown('<div class="sniper-section-heading">Today</div>', unsafe_allow_html=True)
    st.caption("Start here. Green deserves attention now, amber is approaching, red is not worth your time yet. Open Deep Analysis for the full reasoning.")

    for row in ranked:
        dist_text = ""
        if row["distance"] is not None:
            if row["distance"] > 0:
                dist_text = f"{row['distance']:.1f}% above target"
            else:
                dist_text = f"{abs(row['distance']):.1f}% inside/below target"
        target_text = f"Target {row['target']}" if row["target"] else "Target unavailable"
        st.markdown(
            f"""<div style="display:grid;grid-template-columns:minmax(0,1.6fr) minmax(0,1fr) minmax(0,1fr);
                        gap:10px;align-items:center;border-left:8px solid {row['signal_colour']};
                        background:{row['signal_bg']};border-radius:10px;padding:10px 12px;margin:7px 0;">
                <div><b>{row['company']} ({row['ticker']})</b><br>
                     <span style="font-size:1.05rem;">{display_price(row['ticker'],row['price'])}</span></div>
                <div><b>{row['signal']} · {row['signal_label']}</b><br>
                     <span style="font-size:.9rem;">{target_text}</span></div>
                <div><span style="font-size:.92rem;">{dist_text}</span><br>
                     <span style="font-size:.86rem;color:#555;">Score {row['entry_score']}/100</span></div>
            </div>""",
            unsafe_allow_html=True,
        )



st.markdown('<div class="sniper-section-heading">Rock-bottom watch</div>', unsafe_allow_html=True)
st.caption("Special situations we only want at unusually low prices.")

for rb in rock_bottom_rows:
    cfg = rb["cfg"]
    distance_text = (
        f"{abs(rb['distance']):.1f}% below action price"
        if rb["distance"] < 0
        else f"{rb['distance']:.1f}% above action price"
    )
    st.markdown(
        f"""<div style="display:grid;grid-template-columns:minmax(0,1.5fr) minmax(0,1fr) minmax(0,1fr);
                    gap:10px;align-items:center;border-left:8px solid {rb['signal_colour']};
                    background:{rb['signal_bg']};border-radius:10px;padding:10px 12px;margin:7px 0;">
            <div><b>{rb['name']} ({rb['ticker']})</b><br>
                 <span style="font-size:1.05rem;">${rb['price']:,.2f}</span></div>
            <div><b>{rb['signal']} · {rb['signal_text']}</b><br>
                 <span style="font-size:.9rem;">Entry ${cfg['entry_low']:.0f}–${cfg['entry_high']:.0f}</span></div>
            <div><span style="font-size:.92rem;">{distance_text}</span><br>
                 <span style="font-size:.86rem;color:#555;">{rb['direction']}</span></div>
        </div>""",
        unsafe_allow_html=True,
    )


st.markdown('<div class="sniper-section-heading">Deep analysis</div>', unsafe_allow_html=True)
st.caption("Pick a share for the full Sniper view. The chart comes first; the sections below explain whether the current price is genuinely interesting and why.")

tabs=st.tabs(ANALYSIS_UNIVERSE)
for tab,t in zip(tabs,ANALYSIS_UNIVERSE):
    with tab:
        if t not in stocks:
            st.warning("Price data is temporarily unavailable for this share.")
            continue

        d=stocks[t]
        df=d["df"]
        matches=d["matches"]
        price=float(df["Close"].iloc[-1])

        # Calculate the core Sniper snapshot ONCE and reuse it throughout this share.
        snap=rebound_strategy_snapshot(df,matches,stake_gbp)
        label, meaning, instinct=score_explanation(snap["entry_score"])

        # Header: current price + target + traffic light.
        sig,sig_label,sig_colour,sig_bg,zone=all_share_signal(t,price,df)
        target=target_label(t,zone)
        target_suffix=f" (target {target})" if target else ""
        st.markdown(
            f'<div class="sniper-ticker-heading">{COMPANY_NAMES.get(t,t)} ({t}) — '
            f'{display_price(t,price)}{target_suffix} &nbsp; '
            f'{sniper_badge(sig,sig_label,sig_colour,sig_bg)}</div>',
            unsafe_allow_html=True
        )

        # Main chart stays immediately below the share heading.
        st.markdown("### Main price chart")
        mobile_chart(df,t)

        # 1. ONE verdict only.
        st.markdown("### Sniper verdict")
        st.markdown(f"**Buying opportunity: {snap['entry_score']}/100 — {snap['verdict']}**")
        verdict_bits=[]
        if zone:
            lo,hi=zone
            if price > hi:
                gap=(price/hi-1)*100
                verdict_bits.append(f"The current price is {gap:.1f}% above the top of our Sniper target zone ({target}).")
            elif price >= lo:
                verdict_bits.append(f"The share is inside our Sniper target zone ({target}).")
            else:
                verdict_bits.append(f"The share is below our Sniper target zone ({target}), so the reason for the fall needs checking carefully.")
        if snap.get("recent_dip") is not None:
            verdict_bits.append(f"The recent dip is {snap['recent_dip']:.1f}%.")
        verdict_bits.append(meaning)
        st.write(" ".join(verdict_bits))

        # 2. Key signals — RSI explained the FIRST and ONLY time it is surfaced as a section.
        st.markdown("### Key signals")
        recent_high=float(df["Close"].tail(min(66,len(df))).max()) if not df.empty else price
        from_high=(price/recent_high-1)*100 if recent_high else 0.0
        c=df["Close"].astype(float)
        five_day=(price/float(c.iloc[-6])-1)*100 if len(c)>=6 else 0.0

        rsi_value=snap.get("rsi")
        if rsi_value is None:
            # Use the app's RSI helper if snapshot does not expose it.
            try:
                _r=calc_rsi(c)
                rsi_value=float(_r.iloc[-1]) if hasattr(_r,"iloc") else float(_r)
            except Exception:
                rsi_value=None

        if rsi_value is None:
            rsi_text="Unavailable"
        elif rsi_value < 30:
            rsi_text=f"{rsi_value:.0f} — oversold"
        elif rsi_value > 70:
            rsi_text=f"{rsi_value:.0f} — overbought"
        else:
            rsi_text=f"{rsi_value:.0f} — neutral"

        k1,k2,k3,k4=st.columns(4)
        k1.metric("Recent dip", f"{snap.get('recent_dip',0):.1f}%")
        k2.metric("From 3M high", f"{from_high:.1f}%")
        k3.metric("RSI", rsi_text)
        k4.metric("5-day direction", f"{five_day:+.1f}%")
        st.caption("RSI (Relative Strength Index) measures recent price momentum from 0–100. Below 30 usually means heavily sold/oversold; above 70 means heavily bought/overbought. For Sniper, a low RSI can be interesting, especially if it starts turning upward.")

        # 3. What's driving it? Combine market-relative movement + catalysts/news.
        st.markdown("### What's driving the move?")
        try:
            _qqq=load_price("QQQ", years=1)
            _spy=load_price("SPY", years=1)
            _moves=market_move_summary(df,_qqq,_spy)
            _interp=market_move_interpretation(_moves,t)
            if _interp:
                st.write(_interp)
        except Exception:
            pass

        try:
            _news=load_news(t)
            _classified=classify_news(_news) if _news else []
            if _classified:
                for item in _classified[:5]:
                    if isinstance(item, dict):
                        _title=item.get("title") or item.get("headline") or str(item)
                        st.write(f"• {_title}")
                    else:
                        st.write(f"• {item}")
            else:
                st.caption("No significant recent catalyst headlines were returned.")
        except Exception:
            st.caption("Recent catalyst headlines are temporarily unavailable.")

        # Special-situation context belongs here, not in a separate giant section.
        if t=="MSTR":
            st.info("Special situation: Strategy is heavily influenced by Bitcoin. A low MSTR price is not enough on its own — check what Bitcoin is doing and why MSTR has fallen.")
        elif t=="RKLB":
            st.info("Special situation: Rocket Lab carries higher execution risk than the mega-cap names. Check Neutron, launch and company-specific developments before acting.")
        elif t=="SPCX":
            st.info("Special situation: SpaceX has a shorter public trading history, so IPO/unlock/event effects deserve extra weight alongside the normal Sniper analysis.")
        elif t=="BA":
            st.info("Special situation: Boeing can move sharply on operational, regulatory and aircraft-safety developments. Check the cause of any large fall before treating it as a rebound opportunity.")

        # 4. Historical evidence — summary first; detail hidden.
        st.markdown("### Historical Sniper evidence")
        if matches:
            n=len(matches)
            hit10=sum(1 for m in matches if float(m.get("max_gain",0) or 0) >= 10)
            hit20=sum(1 for m in matches if float(m.get("max_gain",0) or 0) >= 20)
            further=[float(m.get("further_fall",0) or 0) for m in matches if m.get("further_fall") is not None]
            sixm=[float(m.get("return_6m",0) or 0) for m in matches if m.get("return_6m") is not None]
            typical_fall=(sum(further)/len(further)) if further else None
            typical_6m=(sum(sixm)/len(sixm)) if sixm else None

            h1,h2,h3,h4=st.columns(4)
            h1.metric("Similar episodes", str(n))
            h2.metric("Later +10%", f"{hit10}/{n}")
            h3.metric("Later +20%", f"{hit20}/{n}")
            h4.metric("Typical further fall", f"{typical_fall:.1f}%" if typical_fall is not None else "n/a")
            if typical_6m is not None:
                st.caption(f"Typical 6-month result across comparable episodes: {typical_6m:+.1f}%.")

            if hit10/n >= .7:
                st.write("Historically, comparable setups have often produced a meaningful rebound, although the share may still fall further before recovering.")
            elif hit10/n >= .4:
                st.write("Historical outcomes are mixed. The setup has produced rebounds before, but the evidence is not strong enough to rely on without the current price/news context.")
            else:
                st.write("Comparable historical setups have not produced a consistently strong rebound. Price alone is not enough here.")

            with st.expander("Show historical examples"):
                try:
                    render_historical_examples(matches,t)
                except Exception:
                    st.dataframe(matches, use_container_width=True)

            with st.expander("Show historical comparison chart"):
                try:
                    analogue_chart(df,matches,t)
                except Exception:
                    st.caption("Historical comparison chart is unavailable for this share.")
        else:
            st.write("There are not enough comparable historical episodes to make the historical evidence meaningful.")

        # 5. Price levels + £20k scenario together.
        st.markdown("### Price levels & £20k scenario")
        p1,p2,p3,p4=st.columns(4)
        p1.metric("Current", display_price(t,price))
        p2.metric("Sniper target", target if target else "n/a")
        if zone:
            entry_reference=zone[1]
            if t.endswith(".L"):
                p3.metric("+10% from target", f"{entry_reference*1.10:,.0f}p")
                p4.metric("+20% from target", f"{entry_reference*1.20:,.0f}p")
            else:
                p3.metric("+10% from target", f"${entry_reference*1.10:,.2f}")
                p4.metric("+20% from target", f"${entry_reference*1.20:,.2f}")
        else:
            p3.metric("+10%", "n/a")
            p4.metric("+20%", "n/a")
        st.caption(f"On a £{stake_gbp:,.0f} position: +10% ≈ £{stake_gbp*.10:,.0f} gross; +20% ≈ £{stake_gbp*.20:,.0f} gross.")

        # 6. Fundamentals & analyst view — ONE section only.
        st.markdown("### Fundamentals & analyst view")
        try:
            _info=load_fundamentals(t)
            _assessment=fundamental_assessment(_info,price) if _info else {}
            if _info:
                _health=_assessment.get("label") or _assessment.get("health") or "Available"
                _pe=_info.get("trailingPE") or _info.get("forwardPE")
                _target=_info.get("targetMeanPrice")
                f1,f2,f3=st.columns(3)
                f1.metric("Fundamental view", str(_health))
                f2.metric("P/E", f"{float(_pe):.1f}x" if _pe else "n/a")
                f3.metric("Analyst mean target", display_price(t,float(_target)) if _target else "n/a")
                with st.expander("Show fundamental details"):
                    _keys=["marketCap","trailingPE","forwardPE","priceToSalesTrailing12Months","revenueGrowth","earningsGrowth","profitMargins","targetMeanPrice","recommendationKey"]
                    _rows={k:_info.get(k) for k in _keys if _info.get(k) is not None}
                    st.dataframe([_rows],use_container_width=True)
            else:
                st.write("Fundamental data is currently unavailable.")
        except Exception:
            st.write("Fundamental data is currently unavailable.")

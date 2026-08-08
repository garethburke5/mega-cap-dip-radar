
import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import numpy as np
import yfinance as yf
import json, math, html
from datetime import datetime, timedelta, timezone

st.set_page_config(page_title="Mega-Cap Sniper", page_icon="🎯", layout="wide")

WATCHLIST = ["TSLA","NVDA","META","AMZN","GOOGL"]
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
    f["3M_DD"]=(c/c.rolling(63).max()-1)*100
    f["6M_DD"]=(c/c.rolling(126).max()-1)*100
    f["12M_DD"]=(c/c.rolling(252).max()-1)*100
    f["RSI"]=calc_rsi(c)
    f["DIST50"]=(c/c.rolling(50).mean()-1)*100
    f["VOLRATIO"]=df["Volume"]/df["Volume"].rolling(20).mean()
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
        fut=c.iloc[pos+1:min(len(c),pos+127)]
        if fut.empty:continue
        best=float((fut.max()/entry-1)*100)
        worst=float((fut.min()/entry-1)*100)
        returns={}
        for lab,d in [("1M",21),("3M",63),("6M",126)]:
            returns[lab]=float((c.iloc[pos+d]/entry-1)*100) if pos+d<len(c) else np.nan
        days={}
        for threshold in [10,20,30]:
            hit=None
            for j in range(pos+1,min(len(c),pos+253)):
                if (float(c.iloc[j])/entry-1)*100>=threshold:
                    hit=j-pos;break
            days[threshold]=hit
        # How far was this signal from the next 6m low?
        low=float(fut.min())
        rows.append({
            "Date":dt.date(),"Similarity":dist,"1M %":returns["1M"],"3M %":returns["3M"],
            "6M %":returns["6M"],"Best 6M %":best,"Further downside %":worst,
            "Days +10%":days[10],"Days +20%":days[20],"Days +30%":days[30],
            "Low proximity %":abs(worst)
        })
    return pd.DataFrame(rows)

def hist_summary(matches,current_price):
    if matches.empty:return {}
    med1=matches["1M %"].median()
    med3=matches["3M %"].median()
    med6=matches["6M %"].median()
    medbest=matches["Best 6M %"].median()
    meddown=matches["Further downside %"].median()
    p10=matches["Days +10%"].notna().mean()*100
    p20=matches["Days +20%"].notna().mean()*100
    p30=matches["Days +30%"].notna().mean()*100
    target_pct=max(0,med6 if pd.notna(med6) else medbest)
    return {
        "n":len(matches),"med1":med1,"med3":med3,"med6":med6,"medbest":medbest,
        "meddown":meddown,"p10":p10,"p20":p20,"p30":p30,
        "target":current_price*(1+target_pct/100),
        "target_pct":target_pct,
        "adverse":current_price*(1+meddown/100),
        "rr": target_pct/abs(meddown) if meddown<0 else np.nan
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
        if hs["p20"]>=70:score+=12; reasons.append("strong historical +20% rebound hit-rate")
        elif hs["p20"]>=50:score+=7; reasons.append("historical analogues are moderately favourable")
        else:cautions.append("similar historical episodes have a weak +20% hit-rate")
        if hs["rr"]==hs["rr"] and hs["rr"]>=2.5:score+=7; reasons.append("historical reward/risk is attractive")
        if hs["meddown"]<-15:cautions.append("similar episodes often suffered substantial further downside")
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

# ---------- CHART ----------
def mobile_chart(df,ticker,entry=None,target=None):
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
    if entry:
        price_lines += f"""series.createPriceLine({{price:{float(entry)},color:'#555',lineWidth:2,lineStyle:2,axisLabelVisible:true,title:'Entry'}});"""
    if target:
        price_lines += f"""series.createPriceLine({{price:{float(target)},color:'#777',lineWidth:2,lineStyle:1,axisLabelVisible:true,title:'Target'}});"""
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
for t in WATCHLIST:
    df=load_price(t,10)
    if df.empty or len(df)<400:continue
    f=feature_frame(df)
    matches=historical_matches(df,f)
    info=load_fundamentals(t)
    current=float(df["Close"].iloc[-1])
    fund_label,fund_notes=fundamental_assessment(info,current)
    engine=opportunity_engine(df,f,matches,qqq5,fund_label)
    hs=hist_summary(matches,current)
    stocks[t]={"df":df,"f":f,"matches":matches,"info":info,"fund_label":fund_label,
               "fund_notes":fund_notes,"engine":engine,"hs":hs}

# ---------- SIDEBAR / POSITION TRACKER ----------
st.sidebar.header("My position (optional)")
held=st.sidebar.selectbox("Stock",["None"]+WATCHLIST)
entry_price=st.sidebar.number_input("Entry price ($)",min_value=0.0,value=0.0,step=1.0)
position_value=st.sidebar.number_input("Amount invested",min_value=0.0,value=0.0,step=500.0)
risk_budget=st.sidebar.number_input("Maximum acceptable loss",min_value=0.0,value=0.0,step=100.0)

# ---------- HOME ----------
st.title("🎯 Mega-Cap Sniper")
st.caption("Find unusually attractive corrections and follow the trade from sell-off to recovery.")

if stocks:
    ranked=sorted(stocks.items(),key=lambda kv:kv[1]["engine"]["score"],reverse=True)
    best_t,best=ranked[0]
    if best["engine"]["score"]>=50:
        st.success(f'BEST OPPORTUNITY TODAY: {best_t} — {best["engine"]["status"]} · {best["engine"]["score"]}/100')
        st.write(best["engine"]["narrative"])
    else:
        st.info("NO COMPELLING SETUP TODAY — none of the five shares currently clears the stronger opportunity threshold.")

    st.subheader("Opportunity board")
    for t,x in ranked:
        df=x["df"]; f=x["f"]; e=x["engine"]; hs=x["hs"]; cur=f.iloc[-1]; price=float(df["Close"].iloc[-1])
        with st.container(border=True):
            st.markdown(f"### {t} · ${price:,.2f}")
            st.markdown(f"**{e['status']} · {e['score']}/100**")
            st.write(f"Today {cur['1D']:+.1f}% · 5D {cur['5D']:+.1f}% · 1M {cur['1M']:+.1f}% · 3M drawdown {cur['3M_DD']:.1f}%")
            if hs:
                st.write(f"Historical setup: {hs['p20']:.0f}% reached +20% · median further downside {hs['meddown']:.1f}% · median 6M outcome {hs['med6']:+.1f}%")
            st.write(f"Fundamentals: {x['fund_label']} · Action: {e['action']}")

st.divider()
st.subheader("Deep analysis")
tabs=st.tabs(WATCHLIST)

for tab,t in zip(tabs,WATCHLIST):
    if t not in stocks:continue
    x=stocks[t]
    with tab:
        df=x["df"]; f=x["f"]; matches=x["matches"]; info=x["info"]; e=x["engine"]; hs=x["hs"]
        cur=f.iloc[-1]; price=float(df["Close"].iloc[-1])

        st.markdown(f"## {t} — {e['status']}")
        a,b,c,d=st.columns(4)
        a.metric("Price",f"${price:,.2f}",f"{cur['1D']:+.1f}% today")
        b.metric("Opportunity",f"{e['score']}/100")
        c.metric("3M drawdown",f"{cur['3M_DD']:.1f}%")
        d.metric("RSI",f"{cur['RSI']:.0f}")

        st.markdown("### Analysis & suggested action")
        st.write(e["narrative"])
        st.write(f"Suggested action: {e['action']}.")
        if e["reasons"]:
            st.write("Why the score is where it is: " + "; ".join(e["reasons"]) + ".")
        if e["cautions"]:
            st.warning("Cautions: " + "; ".join(e["cautions"]) + ".")

        st.markdown("### Price behaviour — in plain English")
        moves=period_rows(df,f)
        st.dataframe(moves.style.format({
            "Was":"${:,.2f}","Now":"${:,.2f}","Move":"${:+,.2f}",
            "Change %":"{:+.1f}%","Tail percentile":"{:.1f}%"
        }),hide_index=True,use_container_width=True)
        st.caption("Tail percentile asks how unusual the move is versus this stock's own history. A very low figure on a decline means unusually severe weakness.")

        # RSI explanation
        if cur["RSI"]<30:rsi_text="oversold territory"
        elif cur["RSI"]<40:rsi_text="weak momentum"
        elif cur["RSI"]<60:rsi_text="roughly neutral momentum"
        elif cur["RSI"]<70:rsi_text="strong momentum"
        else:rsi_text="conventionally overbought territory"
        st.markdown("### RSI explained")
        st.write(f"RSI (Relative Strength Index) measures recent price momentum on a 0–100 scale. {t}'s RSI is {cur['RSI']:.0f}, which indicates {rsi_text}. Below 30 is conventionally called oversold and above 70 overbought, but RSI is not a buy/sell signal by itself.")

        st.markdown("### Historical opportunity engine")
        if hs:
            h1,h2,h3,h4=st.columns(4)
            h1.metric("Similar episodes",hs["n"])
            h2.metric("Reached +20%",f"{hs['p20']:.0f}%")
            h3.metric("Median 6M",f"{hs['med6']:+.1f}%")
            h4.metric("Further downside",f"{hs['meddown']:.1f}%")
            st.write(f"Across the {hs['n']} closest historical setups, the median 1-month outcome was {hs['med1']:+.1f}%, the median 3-month outcome {hs['med3']:+.1f}%, and the median 6-month outcome {hs['med6']:+.1f}%. {hs['p10']:.0f}% reached +10%, {hs['p20']:.0f}% reached +20%, and {hs['p30']:.0f}% reached +30% within the following year.")
            st.write(f"Median further downside after a comparable signal was {hs['meddown']:.1f}%. In other words, historical analogues suggest signals like this were typically within about {abs(hs['meddown']):.1f}% of their subsequent six-month low, although individual outcomes varied considerably.")
            st.dataframe(matches.style.format({
                "Similarity":"{:.2f}","1M %":"{:+.1f}%","3M %":"{:+.1f}%","6M %":"{:+.1f}%",
                "Best 6M %":"{:+.1f}%","Further downside %":"{:+.1f}%","Low proximity %":"{:.1f}%"
            }),hide_index=True,use_container_width=True)

            st.markdown("#### Similar sell-offs — visual comparison")
            st.caption("Current and five closest historical episodes are normalised to 100 so their shapes can be compared. Historical failures are not excluded.")
            analogue_chart(df,matches,t)

        st.markdown("### Trade economics")
        if hs:
            target=hs["target"]; adverse=hs["adverse"]
            q1,q2,q3,q4=st.columns(4)
            q1.metric("Historical median target",f"${target:,.2f}",f"{hs['target_pct']:+.1f}%")
            q2.metric("Historical adverse level",f"${adverse:,.2f}",f"{hs['meddown']:.1f}%")
            q3.metric("Indicative reward/risk",f"{hs['rr']:.1f}:1" if hs['rr']==hs['rr'] else "N/A")
            q4.metric("+20% hit-rate",f"{hs['p20']:.0f}%")
            st.caption("These are scenario estimates derived from comparable historical episodes, not forecasts or guaranteed targets.")

        st.markdown("### Market context")
        st.write(f"{t} 5D: {cur['5D']:+.1f}% · QQQ 5D: {qqq5:+.1f}% · SPY 5D: {spy5:+.1f}% · {t} versus QQQ: {e['rel5']:+.1f} percentage points.")
        if e["rel5"]<-5:
            st.write("Interpretation: the stock has materially underperformed the Nasdaq, suggesting the weakness is substantially stock-specific rather than merely a broad market move.")
        elif e["rel5"]>5:
            st.write("Interpretation: the stock has materially outperformed the Nasdaq over the same period.")
        else:
            st.write("Interpretation: much of the short-term movement is broadly consistent with the wider technology market.")

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

        st.markdown("### Main price chart")
        st.caption("Clean line chart by default. Pinch to zoom, swipe to pan, and tap/drag for the exact date and price.")
        entry_for_chart=entry_price if held==t and entry_price>0 else None
        target_for_chart=hs.get("target") if hs else None
        mobile_chart(df,t,entry_for_chart,target_for_chart)

        if held==t and entry_price>0:
            st.markdown("### My trade")
            ret=(price/entry_price-1)*100
            pnl=position_value*ret/100 if position_value>0 else 0
            if hs and price>=hs["target"]*0.95: lifecycle="TAKE-PROFIT ZONE"
            elif ret>=10:lifecycle="RECOVERY / HOLD"
            elif ret>=0:lifecycle="RECOVERY DEVELOPING"
            elif e["status"]=="DEEP SELLOFF":lifecycle="RISK REVIEW"
            else:lifecycle="ENTRY / WATCH"
            st.write(f"Lifecycle: {lifecycle}")
            st.write(f"Entry ${entry_price:,.2f} → current ${price:,.2f} · return {ret:+.1f}%"
                     + (f" · estimated P/L {pnl:+,.2f}" if position_value>0 else ""))
            if hs and hs["target_pct"]>0:
                expected_total=hs["target"]-entry_price
                achieved=price-entry_price
                pct_done=(achieved/expected_total*100) if expected_total>0 else np.nan
                if pct_done==pct_done:
                    st.write(f"Approximately {pct_done:.0f}% of the move from your entry to the current historical-median target has occurred.")

            if risk_budget>0 and hs and hs["meddown"]<0:
                risk_per_dollar=abs(hs["meddown"])/100
                max_position=risk_budget/risk_per_dollar
                st.write(f"Position-sizing reference: with a {risk_budget:,.0f} maximum loss and historical median adverse move of {abs(hs['meddown']):.1f}%, the corresponding position size would be about {max_position:,.0f}. This is a risk-budget calculation, not a recommendation.")

st.divider()
st.caption("Decision-support only. Historical analogues, analyst targets and technical indicators are not predictions. Review the underlying news and company fundamentals before trading.")

"""Automatic market intelligence with independent sources and calendar fallback."""
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo
from urllib.request import urlopen, Request
from urllib.parse import quote
import json
import calendar
import xml.etree.ElementTree as ET
import streamlit as st
import pandas as pd
import yfinance as yf
from concurrent.futures import ThreadPoolExecutor

UK = ZoneInfo("Europe/London")
NY = ZoneInfo("America/New_York")
TICKERS = ["BARC.L","AVGO","NVDA","GOOGL","TSLA","AMZN","META","QCOM","APP","BAC","IBM","INTC","ARM","MSTR","RKLB","SOFI","PLTR","BA","SPCX","DKS"]
TECH = "AVGO, NVDA, GOOGL, TSLA, AMZN, META, QCOM, APP, IBM, INTC, ARM, PLTR"
BANKS = "BARC.L, BAC, SOFI"
FEED = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
NEXT = "https://nfs.faireconomy.media/ff_calendar_nextweek.json"

def get(url):
    with urlopen(Request(url, headers={"User-Agent":"Mozilla/5.0 ShareSniper/1.0","Accept":"*/*"}), timeout=10) as response:
        return response.read(4_000_000)

def assess(title, country=""):
    t = title.lower()
    uk = country in ("GBP","UK")
    if any(k in t for k in ("cpi","ppi","pce","inflation","consumer price","producer price")):
        return (BANKS if uk else TECH + ", " + BANKS, "High", "If inflation is lower than expected, technology shares could rise as investors expect lower interest rates. Bank shares could move either way.", "If inflation is higher than expected, technology shares could fall as interest rate cuts become less likely. Banks may earn more interest but face more unpaid loans.")
    if any(k in t for k in ("rate","fomc","powell","monetary","fed chair","bailey")):
        return (BANKS if uk else TECH + ", " + BANKS, "Very high", "If the central bank cuts rates or signals earlier cuts than expected, technology shares could rise. Banks may earn less from lending.", "If rates stay higher for longer than expected, technology shares could fall. Banks may earn more from lending, but borrowers could struggle to repay.")
    if any(k in t for k in ("employment","payroll","jobless","jolts","unemployment","adp","gdp","pmi","retail sales")):
        return (BANKS if uk else TECH + ", " + BANKS, "High", "Steady economic growth and falling inflation could encourage investors to buy shares.", "Signs of rising inflation or a weakening economy could cause shares to fall.")
    return (BANKS if uk else "US watchlist", "High", "Better news than investors expect could push shares higher.", "Worse news than expected could cause shares to fall.")

def row(day, time, title, shares, impact, bull, bear, source, status, forecast="", previous=""):
    return {"Date":str(day),"UK time":time,"Event":title,"Shares":shares,"Impact":impact,"What could make shares rise":bull,"What could make shares fall":bear,"Forecast":str(forecast or ""),"Previous":str(previous or ""),"Source":source,"Status":status}

def macro(url):
    out=[]
    for item in json.loads(get(url)):
        if item.get("country") not in ("USD","GBP") or item.get("impact") != "High":
            continue
        when=datetime.fromisoformat(item["date"].replace("Z","+00:00")).astimezone(UK)
        title=item["country"]+" · "+item["title"]
        out.append(row(when.date(),when.strftime("%H:%M"),title,*assess(title,item["country"]),url,"Published calendar",item.get("forecast"),item.get("previous")))
    return out

def earnings(ticker):
    try:
        c=yf.Ticker(ticker).calendar
        if not isinstance(c,dict):
            return []
        dates=c.get("Earnings Date",[])
        if not isinstance(dates,(list,tuple)):
            dates=[dates]
        out=[]
        for d in dates[:1]:
            if not d: continue
            day=pd.Timestamp(d).date()
            related={"AVGO":"AVGO, NVDA, GOOGL, ARM, QCOM, INTC","NVDA":"NVDA, AVGO, ARM, GOOGL, AMZN","GOOGL":"GOOGL, META, AMZN, AVGO","BARC.L":"BARC.L, BAC","AMZN":"AMZN, GOOGL, META, NVDA"}.get(ticker,ticker)
            out.append(row(day,"TBC",ticker+" earnings",related,"Very high","If profits exceed expectations and the company predicts stronger future sales or profits, shares could rise.","If profits disappoint or the company lowers its outlook, shares could fall.", "https://finance.yahoo.com/quote/"+ticker+"/calendar/","Estimated earnings date; not confirmed by the company",c.get("Earnings Average")))
        return out
    except Exception:
        return []

@st.cache_data(ttl=86400)
def thanksgiving_history():
    results=[]
    for ticker in ["SPY","QQQ","AVGO","NVDA","GOOGL","TSLA","BARC.L"]:
        try:
            df=yf.download(ticker,period="20y",auto_adjust=True,progress=False,threads=False)
            close=df["Close"]
            if isinstance(close,pd.DataFrame):
                close=close.iloc[:,0]
            close=close.dropna()
            returns=close.pct_change()
            samples=[]
            for year in range(datetime.now(UK).year-20,datetime.now(UK).year+1):
                thurs=[date(year,11,d) for d in range(1,31) if date(year,11,d).weekday()==3][3]
                monday=thurs+timedelta(days=4)
                if monday>=datetime.now(UK).date(): continue
                matches=returns[returns.index.date==monday].dropna()
                if len(matches): samples.append(float(matches.iloc[0])*100)
            if samples:
                n=len(samples)
                results.append({"Share":ticker,"Years observed":n,"Fell (%)":round(100*sum(x<0 for x in samples)/n,1),"Rose (%)":round(100*sum(x>0 for x in samples)/n,1),"Average move (%)":round(sum(samples)/n,2)})
        except Exception:
            continue
    return results

def seasonal(today,end):
    out=[]
    for offset in range((end-today).days+1):
        d=today+timedelta(days=offset)
        if d.month in (11,12):
            thurs=[date(d.year,11,i) for i in range(1,31) if date(d.year,11,i).weekday()==3][3]
            if d==thurs+timedelta(days=4):
                out.append(row(d,"US session","Monday after Thanksgiving","US watchlist","Medium","Shares may recover if buyers return after the holiday.","Shares may fall as normal trading resumes after the holiday.","Historical price analysis","Recurring holiday pattern; see measured results below"))
        if d.weekday()==4 and 15<=d.day<=21 and d.month in (3,6,9,12):
            out.append(row(d,"US session","Quarterly options expiry","US watchlist","High","As traders close expiring contracts, rising shares could climb faster.","As traders close expiring contracts, falling shares could drop further.","Calendar rule","Scheduled convention; direction uncertain"))
        if d.day==calendar.monthrange(d.year,d.month)[1]:
            trade=d
            while trade.weekday()>4: trade-=timedelta(days=1)
            out.append(row(trade,"Market close","Month-end buying and selling by investment funds","All watchlist","Medium","Investment funds may buy shares that have recently performed poorly, helping them recover.","Investment funds may sell shares that have recently risen sharply, causing prices to fall.","Calendar rule","Seasonal estimate; holidays may shift timing"))
        if d.month==12 and d.day==24:
            out.append(row(d,"Year-end window","Christmas and year-end buying and selling","US watchlist","Medium","End-of-year buying could help shares recover.","Fewer traders and investors selling losing shares for tax reasons could push prices lower.","Calendar rule","Seasonal hypothesis, not a forecast"))
    return out

@st.cache_data(ttl=1800)
def collect(version="2026-11-28-v2"):
    today=datetime.now(UK).date()
    end=today+timedelta(days=30)
    rows=seasonal(today,end)
    errors=[]
    with ThreadPoolExecutor(max_workers=6) as pool:
        jobs=[(url,pool.submit(macro,url)) for url in (FEED,NEXT)]
        earnings_jobs=[pool.submit(earnings,t) for t in TICKERS]
        for url,f in jobs:
            try: rows.extend(f.result())
            except Exception: errors.append(url)
        for f in earnings_jobs:
            rows.extend(f.result())
    # Verified December schedule, retained even if external feeds reject requests.
    for day,clock,title in [(1,"15:00","US job openings (JOLTS)"),(4,"13:30","US non-farm payrolls (Employment Situation)"),(10,"13:30","US CPI inflation"),(15,"13:30","US PPI inflation")]:
        d=date(2026,12,day)
        if today<=d<=end and not any(x["Date"]==str(d) and any(k in x["Event"].lower() for k in {1:["jolts","job openings"],4:["nonfarm","non-farm","employment situation"],10:["cpi","consumer price"],15:["ppi","producer price"]}[day]) for x in rows):
            rows.append(row(d,clock,title,*assess(title),"https://www.bls.gov/schedule/2026/12_sched_list.htm","Official schedule verified 28 Nov 2026"))
    # Ensure holiday event survives cached or partial calendars.
    for event in seasonal(today,end):
        if not any(x["Date"]==event["Date"] and x["Event"]==event["Event"] for x in rows):
            rows.append(event)
    # Official calendar links are provenance, not a substitute for populated events.
    # Independent dated fallback for the December 2026 FOMC meeting.
    d=date(2026,12,9)
    if today<=d<=end and not any(x["Date"]==str(d) and ("federal funds rate" in x["Event"].lower() or "fomc statement" in x["Event"].lower()) for x in rows):
        rows.append(row(d,"19:00","US Federal Reserve interest rate decision",*assess("FOMC"),"https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm","Published meeting schedule"))
    return sorted([x for x in rows if str(today)<=x["Date"]<=str(end)],key=lambda x:(x["Date"],x["UK time"],x["Event"])),errors

@st.cache_data(ttl=900)
def headlines():
    queries=["Federal Reserve inflation tariffs stock market","Broadcom Nvidia Alphabet AI chip earnings export restrictions","Barclays UK banks Bank of England regulation"]
    out=[]
    for q in queries:
        try:
            url="https://news.google.com/rss/search?q="+quote(q+" when:2d")+"&hl=en-GB&gl=GB&ceid=GB:en"
            root=ET.fromstring(get(url))
            for item in root.findall("./channel/item")[:4]:
                title=item.findtext("title","")
                lower=title.lower()
                shares= "BARC.L" if any(k in lower for k in ("uk banks","u.k. banks","bank of england","lloyds","barclays","boe","major banks")) else TECH
                out.append((title,item.findtext("link",""),shares,item.findtext("pubDate","")))
        except Exception:
            continue
    return out

def numeric(value):
    try:
        return float(str(value).strip().replace("%","").replace(",",""))
    except (ValueError, TypeError):
        return None

def outlook(event):
    title=event["Event"].lower()
    forecast=event["Forecast"]
    previous=event["Previous"]
    f,p=numeric(forecast),numeric(previous)
    if any(k in title for k in ("federal funds rate","bank rate","official bank rate","interest rate decision")):
        if f is not None and p is not None and "%" in forecast and "%" in previous:
            delta=round(f-p,2)
            action=("Keep rates unchanged" if delta==0 else ("Cut" if delta<0 else "Raise")+" rates by "+f"{abs(delta):.2f}"+" percentage points")
            return action+" to "+forecast+".", ("Technology shares may benefit from lower rates" if delta<0 else "Higher rates may weigh on technology shares" if delta>0 else "No clear direction from the rate decision alone")+". The expected decision may already be reflected in prices; the statement could matter more.", "Based on published calendar forecast, not a separate probability model."
        return "Rate decision forecast unavailable.", "No reliable directional call without current rate expectations.", "Insufficient data."
    if any(k in title for k in ("cpi","ppi","pce","inflation","consumer price","producer price")) and f is not None and p is not None:
        direction="rise" if f>p else "fall" if f<p else "stay unchanged"
        bias="Potential support for technology shares if inflation cools." if f<p else "Potential pressure on technology shares if inflation rises." if f>p else "No clear directional advantage from the expected reading."
        return "Inflation reading expected to "+direction+" from "+previous+" to "+forecast+".",bias+" A result matching expectations may already be reflected in prices.","Based on calendar forecast; low confidence in share direction."
    if forecast:
        return "Published forecast: "+forecast+".", "No reliable directional edge established from this forecast alone.", "Consensus estimate, not an independent prediction."
    return "No reliable forecast available.", "No evidence-based directional call yet.", "Insufficient data."

@st.cache_data(ttl=86400)
def historical_prices(ticker):
    try:
        df=yf.download(ticker,period="20y",auto_adjust=True,progress=False,threads=False)
        c=df["Close"]
        if isinstance(c,pd.DataFrame): c=c.iloc[:,0]
        return c.dropna()
    except Exception:
        return pd.Series(dtype=float)

@st.cache_data(ttl=86400)
def earnings_dates(ticker):
    try:
        df=yf.Ticker(ticker).get_earnings_dates(limit=100)
        return [(x.date(),x.hour) for x in df.index] if df is not None else []
    except Exception:
        return []

@st.cache_data(ttl=86400)
def release_dates(series):
    # FRED release calendar, public CSV-style HTML table; actual dates only.
    try:
        tables=pd.read_html("https://fred.stlouisfed.org/releases/calendar?rid="+str(series)+"&view=year")
        dates=[]
        for table in tables:
            for col in table.columns:
                if "date" in str(col).lower():
                    dates.extend(pd.to_datetime(table[col],errors="coerce").dropna().dt.date.tolist())
        return sorted(set(dates))
    except Exception:
        return []

def historical_event(event,ticker):
    c=historical_prices(ticker)
    if c.empty: return [],"Price history unavailable"
    days=list(c.index.date)
    title=event["Event"].lower()
    cutoff=datetime.now(UK).date()
    positions=[]
    if "earnings" in title:
        company=event["Event"].split()[0]
        for d,hour in earnings_dates(company):
            if d>=cutoff: continue
            # After-close announcements are measured on the next session.
            candidates=[i for i,x in enumerate(days) if x>d or (x==d and hour<16)]
            if candidates: positions.append(candidates[0])
        basis="Past reported earnings dates; announcement timing may be approximate"
    elif "thanksgiving" in title:
        for i,d in enumerate(days):
            thurs=[date(d.year,11,j) for j in range(1,31) if date(d.year,11,j).weekday()==3][3]
            if d==thurs+timedelta(days=4): positions.append(i)
        basis="Equivalent Monday after Thanksgiving"
    elif "month-end" in title:
        positions=[i for i in range(len(days)-1) if days[i].month!=days[i+1].month]
        basis="Last trading session of each month"
    elif "options expiry" in title:
        positions=[i for i,d in enumerate(days) if d.month in (3,6,9,12) and d.weekday()==4 and 15<=d.day<=21]
        basis="Third Friday of quarterly expiry months; holiday shifts not included"
    elif "christmas" in title:
        positions=[i for i,d in enumerate(days) if d.month==12 and d.day>=24 and (i==0 or days[i-1].day<24)]
        basis="First trading session on or after 24 December"
    else:
        # Never substitute approximate monthly dates for actual release dates.
        ids=[(("cpi","consumer price"),10),(("ppi","producer price"),46),(("employment situation","non-farm","nonfarm"),50),(("jolts","job openings"),192),(("fomc","federal reserve interest rate","federal funds rate"),101)]
        rid=next((v for keys,v in ids if any(k in title for k in keys)),None) if "gbp" not in title and "uk " not in title else None
        if rid is None: return [],"Verified historical event dates not available for this event"
        dates=set(release_dates(rid))
        positions=[i for i,d in enumerate(days) if d in dates]
        basis="Published FRED release dates; available calendar history only"
    values=[float((c.iloc[i]/c.iloc[i-1]-1)*100) for i in sorted(set(positions)) if i>0 and days[i]<cutoff and c.iloc[i-1]>0]
    return values,basis

@st.cache_data(ttl=1800)
def directional_view(event):
    title=event["Event"].lower()
    ticker="BARC.L" if "gbp" in title or "uk " in title else "QQQ"
    if "earnings" in title: ticker=event["Event"].split()[0]
    values,basis=historical_event(event,ticker)
    score=0
    reasons=[]
    if len(values)>=10:
        up=sum(v>0 for v in values)/len(values)
        avg=sum(values)/len(values)
        if up>=.60 and avg>0: score+=2
        elif up<=.40 and avg<0: score-=2
        reasons.append(f"{ticker} rose in {up:.0%} of {len(values)} comparable sessions; average move {avg:+.2f}%.")
    f,p=numeric(event["Forecast"]),numeric(event["Previous"])
    if f is not None and p is not None:
        if any(k in title for k in ("cpi","ppi","pce","inflation","federal funds rate","bank rate","interest rate decision")) and ticker!="BARC.L":
            score+=1 if f<p else -1 if f>p else 0
            reasons.append("Published forecast points to "+("lower" if f<p else "higher" if f>p else "unchanged")+" inflation or rates. Expected news may already be reflected in prices.")
    if score>0: view="Lean towards rising prices"
    elif score<0: view="Lean towards falling prices"
    else: view="No clear advantage"
    confidence="Moderate historical support" if abs(score)>=2 and len(values)>=20 else "Low confidence"
    if not reasons: reasons=["No comparable event history or usable forecast was retrieved. A directional prediction would be guesswork."]
    return view,confidence," ".join(reasons)

def render_history(event):
    with st.expander("Historical evidence and likely direction"):
        tickers=["SPY","QQQ"] if "GBP" not in event["Event"] else ["BARC.L"]
        tickers+= [t for t in TICKERS if t in event["Shares"].split(", ")][:4]
        rows=[]
        for ticker in dict.fromkeys(tickers):
            values,basis=historical_event(event,ticker)
            if not values:
                continue
            n=len(values)
            up=100*sum(v>0 for v in values)/n
            down=100*sum(v<0 for v in values)/n
            avg=sum(values)/n
            direction="More often rose" if n>=10 and up>=60 and avg>0 else "More often fell" if n>=10 and down>=60 and avg<0 else "No clear pattern"
            rows.append({"Share":ticker,"Past events":n,"Rose %":round(up,1),"Fell %":round(down,1),"Average move %":round(avg,2),"Historical direction":direction,"Basis":basis})
        if rows:
            st.dataframe(pd.DataFrame(rows),hide_index=True,use_container_width=True)
            st.caption("Previous close to event-session close. Historical frequency is not a forecast probability; other news can affect returns. Fewer than 10 observations are insufficient for a directional call.")
        else:
            st.caption("No verified historical sample available for this event. No historical direction has been invented.")

def render_catalysts():
    st.subheader("Market intelligence · Upcoming catalysts")
    st.caption("Automatic calendar and earnings estimates · UK time · What could make shares rise or fall. These are possibilities, not guarantees.")
    rows,errors=collect()
    if errors:
        st.caption("Some macro feeds are unavailable; earnings and seasonal events remain independent. Coverage is incomplete.")
    if rows:
        for event in rows:
            with st.container():
                st.markdown("**"+event["Date"]+" · "+event["UK time"]+" — "+event["Event"]+"**")
                st.caption(event["Impact"]+" impact · "+event["Shares"]+" · "+event["Status"])
                if "earnings" in event["Event"].lower() and event["Forecast"]:
                    st.write("Expected earnings per share: "+str(round(float(event["Forecast"]),2)) if numeric(event["Forecast"]) is not None else "Expected earnings per share: "+event["Forecast"])
                elif event["Forecast"] or event["Previous"]:
                    st.write("Forecast: "+(event["Forecast"] or "Unavailable")+" | Previous: "+(event["Previous"] or "Unavailable"))
                prediction, bias, basis = outlook(event)
                st.markdown("**Expected outcome:** "+prediction)
                view, confidence, reasoning = directional_view(event)
                st.markdown("**Share Sniper view: "+view+"**")
                st.write(reasoning)
                st.caption(confidence+" · Rule-based estimate, not a measured probability.")
                st.write("**Effect of expected outcome:** "+bias)
                st.caption(basis)
                st.write("🟢 Could rise: "+event["What could make shares rise"])
                st.write("🔴 Could fall: "+event["What could make shares fall"])
                if event["Source"].startswith("https://"):
                    st.markdown("[Source]("+event["Source"]+")")
                render_history(event)
                st.divider()
    else:
        st.warning("No upcoming events returned. Coverage is incomplete.")
    st.markdown("### Developing market news")
    news=headlines()
    if not news:
        st.caption("News feed currently unavailable.")
    for title,link,shares,published in news:
        st.markdown("**"+title+"**")
        st.caption("Shares potentially affected: "+shares+" · "+published)
        lower=title.lower()
        if shares=="BARC.L" and any(k in lower for k in ("capital requirements","capital rules","capital rule","shakeup")):
            st.write("Likely positive for Barclays if banks are allowed to hold less capital: more money could be available for lending, dividends and share buybacks. The details and existing expectations matter.")
        elif "tariff" in lower:
            st.write("Potentially negative for technology shares: higher import costs could reduce profits and keep interest rates higher. Actual tariff scope and timing matter.")
        else:
            st.write("No clear direction from this headline alone.")
        if link.startswith("https://"): st.markdown("[Original headline]("+link+")")
    st.caption("Macro feed covers current and next week; earnings estimates cover 30 days where supplied. News is headline-based, not verified full-text analysis. Historical comparisons are shown where event dates and prices are available; advance alerts are not yet implemented.")

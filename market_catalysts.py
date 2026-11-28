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
        return (BANKS if uk else TECH + ", " + BANKS, "High", "Below forecast: lower yields may lift growth shares; banks mixed.", "Above forecast: higher yields may pressure growth; banks face credit/rate trade-offs.")
    if any(k in t for k in ("rate","fomc","powell","monetary","fed chair","bailey")):
        return (BANKS if uk else TECH + ", " + BANKS, "Very high", "Dovish surprise may lift equities; bank margins may narrow.", "Hawkish surprise may pressure valuations; bank impact depends on yield curve and credit.")
    if any(k in t for k in ("employment","payroll","jobless","jolts","unemployment","adp","gdp","pmi","retail sales")):
        return (BANKS if uk else TECH + ", " + BANKS, "High", "Resilient growth with cooling inflation supports risk appetite.", "Overheating or recession signals may trigger selling.")
    return (BANKS if uk else "US watchlist", "High", "Better-than-priced outcome may support shares.", "Adverse surprise may weaken sentiment.")

def row(day, time, title, shares, impact, bull, bear, source, status, forecast="", previous=""):
    return {"Date":str(day),"UK time":time,"Event":title,"Shares":shares,"Impact":impact,"Upside trigger":bull,"Downside trigger":bear,"Forecast":str(forecast or ""),"Previous":str(previous or ""),"Source":source,"Status":status}

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
            out.append(row(day,"TBC",ticker+" earnings",related,"Very high","Beat expectations and raise guidance: potential rally.","Miss expectations or cut guidance: potential sell-off.", "https://finance.yahoo.com/quote/"+ticker+"/calendar/","Provider estimate; verify company confirmation",c.get("Earnings Average")))
        return out
    except Exception:
        return []

def seasonal(today,end):
    out=[]
    for offset in range((end-today).days+1):
        d=today+timedelta(days=offset)
        if d.weekday()==4 and 15<=d.day<=21 and d.month in (3,6,9,12):
            out.append(row(d,"US session","Quarterly options expiry","US watchlist","High","Position unwinds can amplify rebounds.","Position unwinds can amplify sell-offs.","Calendar rule","Scheduled convention; direction uncertain"))
        if d.day==calendar.monthrange(d.year,d.month)[1]:
            trade=d
            while trade.weekday()>4: trade-=timedelta(days=1)
            out.append(row(trade,"Market close","Month-end portfolio rebalancing","All watchlist","Medium","Allocation flows may support laggards.","Allocation flows may pressure recent winners.","Calendar rule","Seasonal estimate; holidays may shift timing"))
        if d.month==12 and d.day==24:
            out.append(row(d,"Year-end window","Holiday liquidity / tax-loss selling / Santa rally window","US watchlist","Medium","Seasonal buying or rebound in beaten-down shares.","Thin liquidity and tax-loss selling can extend declines.","Calendar rule","Seasonal hypothesis, not a forecast"))
    return out

@st.cache_data(ttl=1800)
def collect():
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
    # Official calendar links are provenance, not a substitute for populated events.
    # Independent dated fallback for the December 2026 FOMC meeting.
    d=date(2026,12,9)
    if today<=d<=end and not any(x["Date"]==str(d) and ("federal funds rate" in x["Event"].lower() or "fomc statement" in x["Event"].lower()) for x in rows):
        rows.append(row(d,"19:00","Federal Reserve policy decision",*assess("FOMC"),"https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm","Published meeting schedule"))
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
                shares= BANKS if "barclays" in lower or "bank of england" in lower else TECH
                out.append((title,item.findtext("link",""),shares,item.findtext("pubDate","")))
        except Exception:
            continue
    return out

def render_catalysts():
    st.subheader("Market intelligence · Upcoming catalysts")
    st.caption("Automatic calendar and earnings estimates · UK time · Conditional impact, not a guaranteed price forecast.")
    rows,errors=collect()
    if errors:
        st.caption("Some macro feeds are unavailable; earnings and seasonal events remain independent. Coverage is incomplete.")
    if rows:
        for event in rows:
            with st.container():
                st.markdown("**"+event["Date"]+" · "+event["UK time"]+" — "+event["Event"]+"**")
                st.caption(event["Impact"]+" impact · "+event["Shares"]+" · "+event["Status"])
                if event["Forecast"] or event["Previous"]:
                    st.write("Forecast: "+(event["Forecast"] or "Unavailable")+" | Previous: "+(event["Previous"] or "Unavailable"))
                st.write("🟢 "+event["Upside trigger"])
                st.write("🔴 "+event["Downside trigger"])
                if event["Source"].startswith("https://"):
                    st.markdown("[Source]("+event["Source"]+")")
                st.divider()
    else:
        st.warning("No upcoming events returned. Coverage is incomplete.")
    st.markdown("### Developing market news")
    news=headlines()
    if not news:
        st.caption("News feed currently unavailable.")
    for title,link,shares,published in news:
        st.markdown("**"+title+"**")
        st.caption("Potential exposure: "+shares+" · "+published)
        st.write("Direction unconfirmed: assess whether the development improves or worsens earnings, policy or risk expectations.")
        if link.startswith("https://"): st.markdown("[Original headline]("+link+")")
    st.caption("Macro feed covers current and next week; earnings estimates cover 30 days where supplied. News is headline-based, not verified full-text analysis. Historical event backtests and advance alerts are not yet implemented.")

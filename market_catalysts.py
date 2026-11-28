"""Forward-looking catalyst calendar; official BLS feed, no paid API."""
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo
from urllib.request import urlopen
import re
import streamlit as st
import pandas as pd

BLS = "https://www.bls.gov/schedule/news_release/bls.ics"
UK = ZoneInfo("Europe/London")
ET = ZoneInfo("America/New_York")

@st.cache_data(ttl=3600)
def load_bls():
    with urlopen(BLS, timeout=12) as response:
        raw = response.read(2_000_000).decode("utf-8-sig")
    raw = re.sub(r"\r?\n[ \t]", "", raw)
    rows = []
    for block in raw.split("BEGIN:VEVENT")[1:]:
        fields = {}
        for line in block.split("END:VEVENT")[0].splitlines():
            key, sep, value = line.partition(":")
            if sep:
                fields[key.split(";")[0]] = (key, value)
        title = fields.get("SUMMARY", ("", ""))[1].replace("\\,", ",")
        key, stamp = fields.get("DTSTART", ("", ""))
        if not title or not stamp:
            continue
        try:
            if len(stamp) == 8:
                when = datetime.strptime(stamp, "%Y%m%d").replace(tzinfo=ET)
                timed = False
            else:
                when = datetime.strptime(stamp.rstrip("Z"), "%Y%m%dT%H%M%S")
                when = when.replace(tzinfo=ZoneInfo("UTC") if stamp.endswith("Z") else ET)
                timed = True
            when = when.astimezone(UK)
        except ValueError:
            continue
        lower = title.lower()
        if any(x in lower for x in ("consumer price", "producer price", "employment situation", "job openings", "employment cost")):
            rows.append((when, timed, title))
    return rows

def render_catalysts():
    st.subheader("Market intelligence · Upcoming catalysts")
    st.caption("Next 30 days · UK time · Event risk is not a prediction of direction.")
    today = datetime.now(UK).date()
    end = today + timedelta(days=30)
    rows = []
    try:
        for when, timed, title in load_bls():
            if today <= when.date() <= end:
                inflation = "price index" in title.lower()
                rows.append({"Date": when.strftime("%Y-%m-%d"), "UK time": when.strftime("%H:%M") if timed else "Not specified", "Event": title, "Exposure": "US equities; UK banks indirectly", "Rally scenario": "Cooler inflation / softer yields" if inflation else "Orderly labour cooling", "Sell-off scenario": "Hotter inflation / higher yields" if inflation else "Hot jobs or recession fears", "Source": BLS})
        if not rows:
            st.info("No matching BLS releases returned for this window. Check the official calendar.")
    except Exception:
        st.warning("BLS calendar unavailable. No release dates have been guessed.")
    if rows:
        st.dataframe(pd.DataFrame(rows).sort_values(["Date","UK time"]), hide_index=True, use_container_width=True)
    st.caption("Source: US Bureau of Labor Statistics. Feed cached for one hour; release schedules can change.")
    st.markdown("**Other official calendars — check before trading**")
    st.markdown("[Federal Reserve decisions](https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm) · [Bank of England decisions](https://www.bankofengland.co.uk/monetary-policy/upcoming-mpc-dates) · [UK inflation and releases](https://www.ons.gov.uk/releasecalendar) · [US GDP and PCE](https://www.bea.gov/news/schedule) · [Broadcom investor relations](https://investors.broadcom.com/) · [Nvidia investor relations](https://investor.nvidia.com/)")
    with st.expander("Seasonal and trading considerations"):
        st.write("Month-end rebalancing, quarterly options expiry, holiday-shortened sessions and year-end tax-loss selling may affect liquidity. Holiday rallies and post-holiday reversals are hypotheses, not reliable forecasts. Check the actual price, news and volume before acting.")
        st.caption("Share-specific event backtests, consensus forecasts and automated event alerts are not yet integrated.")

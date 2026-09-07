from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

BASE = "https://www.allsop.co.uk"
INDEX = BASE + "/auctions/all-past-auction-results/"
OUT = Path("auction_history_output")
MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def norm(s):
    return re.sub(r"\s+", " ", s or "").strip()


def month_key(text):
    m = re.search(
        r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(20\d{2})\b",
        text or "", re.I,
    )
    if not m:
        return None
    return f"{int(m.group(2)):04d}-{MONTHS[m.group(1).lower()]:02d}"


def fetch_requests(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131 Safari/537.36",
        "Accept-Language": "en-GB,en;q=0.9",
    }
    r = requests.get(url, headers=headers, timeout=30)
    r.raise_for_status()
    return r.text, {"method": "requests", "status": r.status_code, "bytes": len(r.content), "final_url": r.url}


def fetch_browser(url):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131 Safari/537.36"
        )
        response = page.goto(url, wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(1500)
        html = page.content()
        meta = {
            "method": "playwright",
            "status": response.status if response else None,
            "bytes": len(html.encode("utf-8")),
            "final_url": page.url,
            "title": page.title(),
        }
        browser.close()
        return html, meta


def parse_index(html):
    soup = BeautifulSoup(html, "html.parser")
    anchors = []
    in_commercial = False
    current_label = None
    diagnostics = []

    for node in soup.find_all(["h2", "h3", "h4", "h5", "h6", "li", "a", "div", "p"]):
        text = norm(node.get_text(" ", strip=True))
        if not text:
            continue
        low = text.casefold()
        if low == "commercial auctions":
            in_commercial = True
            diagnostics.append("ENTER COMMERCIAL: " + text)
            continue
        if low == "residential auctions":
            if in_commercial:
                diagnostics.append("LEAVE COMMERCIAL: " + text)
            in_commercial = False
            continue
        if not in_commercial:
            continue
        mk = month_key(text)
        if mk:
            current_label = text
        if node.name != "a" or not node.get("href"):
            continue
        href = urljoin(BASE, node.get("href"))
        if "property-search" not in href or "auction_id=" not in href:
            continue
        qs = parse_qs(urlparse(href).query)
        auction_id = (qs.get("auction_id") or [None])[0]
        if not auction_id:
            continue
        label = current_label or text
        anchors.append({
            "auction_id": auction_id,
            "label": label,
            "month": month_key(label),
            "results_url": href,
            "source_index_url": INDEX,
        })

    # Fallback: inspect every auction_id link if section semantics changed.
    if not anchors:
        for a in soup.find_all("a", href=True):
            href = urljoin(BASE, a.get("href"))
            if "property-search" not in href or "auction_id=" not in href:
                continue
            qs = parse_qs(urlparse(href).query)
            auction_id = (qs.get("auction_id") or [None])[0]
            if not auction_id:
                continue
            nearby = norm(a.parent.get_text(" ", strip=True)) if a.parent else norm(a.get_text(" ", strip=True))
            # Keep only links whose nearby context says Commercial.
            if "commercial" not in nearby.casefold():
                continue
            anchors.append({
                "auction_id": auction_id,
                "label": nearby[:500],
                "month": month_key(nearby),
                "results_url": href,
                "source_index_url": INDEX,
            })

    dedup = {x["auction_id"]: x for x in anchors}
    auctions = sorted(dedup.values(), key=lambda x: x.get("month") or "", reverse=True)
    headings = [norm(h.get_text(" ", strip=True)) for h in soup.find_all(["h1", "h2", "h3", "h4"])]
    auction_links = [urljoin(BASE, a.get("href")) for a in soup.find_all("a", href=True) if "auction_id=" in a.get("href", "")]
    return auctions, {
        "headings": headings[:100],
        "auction_id_link_count": len(auction_links),
        "sample_auction_links": auction_links[:30],
        "section_trace": diagnostics[:100],
    }


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    attempts = []
    html = None
    try:
        html, meta = fetch_requests(INDEX)
        attempts.append({"ok": True, **meta})
    except Exception as exc:
        attempts.append({"ok": False, "method": "requests", "error": f"{type(exc).__name__}: {exc}"})

    auctions = []
    parse_diag = {}
    if html:
        auctions, parse_diag = parse_index(html)

    if not auctions:
        try:
            html, meta = fetch_browser(INDEX)
            attempts.append({"ok": True, **meta})
            auctions, parse_diag = parse_index(html)
        except Exception as exc:
            attempts.append({"ok": False, "method": "playwright", "error": f"{type(exc).__name__}: {exc}"})

    payload = {
        "schema_version": 1,
        "generated_at": now_iso(),
        "source": "Allsop Commercial",
        "index_url": INDEX,
        "status": "DISCOVERED" if auctions else "NO_AUCTIONS_FOUND",
        "auctions_discovered": len(auctions),
        "earliest_month": min((x["month"] for x in auctions if x.get("month")), default=None),
        "latest_month": max((x["month"] for x in auctions if x.get("month")), default=None),
        "attempts": attempts,
        "diagnostics": parse_diag,
        "auctions": auctions,
    }
    (OUT / "allsop_discovery.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    (OUT / "progress.json").write_text(json.dumps({
        "schema_version": 1,
        "updated_at": now_iso(),
        "sources": {
            "Allsop Commercial": {
                "status": payload["status"],
                "auctions_discovered": len(auctions),
                "earliest_month_reached": payload["earliest_month"],
                "latest_month_seen": payload["latest_month"],
            }
        }
    }, indent=2), encoding="utf-8")
    print(json.dumps({
        "status": payload["status"],
        "auctions_discovered": len(auctions),
        "earliest_month": payload["earliest_month"],
        "latest_month": payload["latest_month"],
        "attempts": attempts,
    }, indent=2))
    if not auctions:
        raise SystemExit(2)


if __name__ == "__main__":
    main()

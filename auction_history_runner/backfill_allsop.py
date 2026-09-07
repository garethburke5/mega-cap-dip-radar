from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE = "https://www.allsop.co.uk"
OUT = Path("auction_history_output")
DISCOVERY = OUT / "allsop_discovery.json"
PROGRESS = OUT / "progress.json"
LOTS = OUT / "allsop_lots.json"
POSTCODE = re.compile(r"\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b", re.I)


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def norm(value):
    return re.sub(r"\s+", " ", value or "").strip()


def money(patterns, text):
    for pattern in patterns:
        m = re.search(pattern, text, re.I)
        if m:
            try:
                return float(m.group(1).replace(",", ""))
            except ValueError:
                pass
    return None


def request_html(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131 Safari/537.36",
        "Accept-Language": "en-GB,en;q=0.9",
    }
    r = requests.get(url, headers=headers, timeout=35)
    r.raise_for_status()
    return r.text


def browser_html(url):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131 Safari/537.36"
        )
        page.goto(url, wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(1200)
        html = page.content()
        browser.close()
        return html


def extract_lot_links(html):
    soup = BeautifulSoup(html, "html.parser")
    found = []
    for a in soup.find_all("a", href=True):
        href = urljoin(BASE, a.get("href"))
        if "/lot-overview/" not in href:
            continue
        href = href.split("?", 1)[0]
        if href not in found:
            found.append(href)
    return found


def lot_links(results_url):
    links = extract_lot_links(request_html(results_url))
    if links:
        return links, "requests"
    return extract_lot_links(browser_html(results_url)), "playwright"


def status_from(text):
    if re.search(r"\bsold\s+prior\b", text, re.I):
        return "SOLD PRIOR"
    if re.search(r"\bsold\b", text, re.I):
        return "SOLD"
    if re.search(r"\bwithdrawn\b", text, re.I):
        return "WITHDRAWN"
    if re.search(r"\bpostponed\b", text, re.I):
        return "POSTPONED"
    if re.search(r"\bunsold\b|\bnot sold\b", text, re.I):
        return "UNSOLD"
    return "ARCHIVED"


def extract_address(main):
    strings = [norm(x) for x in main.stripped_strings]
    lot_number = None
    address = None
    for i, text in enumerate(strings[:160]):
        m = re.fullmatch(r"LOT\s+(\d+[A-Z]?)\s*-\s*.+", text, re.I)
        if m:
            lot_number = f"Lot {m.group(1)}"
            for candidate in strings[i + 1:i + 14]:
                if POSTCODE.search(candidate) and 8 <= len(candidate) <= 260:
                    address = candidate
                    break
            break
    if not address:
        for text in strings[:140]:
            if POSTCODE.search(text) and 8 <= len(text) <= 260 and not re.search(r"guide price|register to bid|finance", text, re.I):
                address = text
                break
    if not lot_number:
        page_text = norm(main.get_text(" ", strip=True))
        m = re.search(r"\bLOT\s+(\d+[A-Z]?)\b", page_text, re.I)
        if m:
            lot_number = f"Lot {m.group(1)}"
    return lot_number or "Lot TBC", address


def exact_date(text, fallback):
    m = re.search(r"(?:offered\s+on|auction(?:ed)?(?: on)?|auction date\.?)[^\d]{0,40}(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)(?:\s+(20\d{2}))?", text, re.I)
    if not m:
        return fallback
    months = {
        "january":"01","february":"02","march":"03","april":"04","may":"05","june":"06",
        "july":"07","august":"08","september":"09","october":"10","november":"11","december":"12",
        "jan":"01","feb":"02","mar":"03","apr":"04","jun":"06","jul":"07","aug":"08","sep":"09","sept":"09","oct":"10","nov":"11","dec":"12",
    }
    mm = months.get(m.group(2).lower())
    if not mm:
        return fallback
    year = m.group(3) or (fallback[:4] if fallback else None)
    return f"{year}-{mm}-{int(m.group(1)):02d}" if year else fallback


def hydrate(url, auction):
    try:
        html = request_html(url)
        soup = BeautifulSoup(html, "html.parser")
        main = soup.find("main") or soup
        text = norm(main.get_text(" ", strip=True))
        lot_number, address = extract_address(main)
        if not address:
            return {"_error": "address_not_found", "url": url}
        h1 = main.find("h1") or soup.find("h1")
        title = norm(h1.get_text(" ", strip=True)) if h1 else None
        image = None
        og = soup.find("meta", attrs={"property": "og:image"})
        if og and og.get("content"):
            image = urljoin(url, og.get("content"))
        guide = money([
            r"Guide Price(?:\s*[:\-])?\s*£\s*([\d,]+(?:\.\d{1,2})?)",
            r"Guide(?:\s*[:\-])?\s*£\s*([\d,]+(?:\.\d{1,2})?)",
        ], text)
        sold = money([
            r"\bSold(?:\s+Prior)?(?:\s+for|\s+at)?\s*£\s*([\d,]+(?:\.\d{1,2})?)",
            r"\bSale Price\s*£\s*([\d,]+(?:\.\d{1,2})?)",
            r"\bResult\s*£\s*([\d,]+(?:\.\d{1,2})?)",
        ], text)
        annual_rent = money([
            r"(?:current\s+)?(?:annual\s+)?rent(?:al)?(?:\s+income)?(?:\s*[:\-]|\s+of)?\s*£\s*([\d,]+(?:\.\d{1,2})?)",
            r"£\s*([\d,]+(?:\.\d{1,2})?)\s*(?:per annum|p\.a\.|pa\b)",
        ], text)
        tenure = None
        if re.search(r"\bfreehold\b", text, re.I):
            tenure = "Freehold"
        elif re.search(r"\blong leasehold\b|\bleasehold\b", text, re.I):
            tenure = "Leasehold"
        fallback = f"{auction.get('month')}-01" if auction.get("month") else None
        return {
            "source": "Allsop Commercial",
            "source_id": auction.get("auction_id"),
            "url": url,
            "result_page_url": auction.get("results_url"),
            "address": address,
            "lot_number": lot_number,
            "auction_date": exact_date(text, fallback),
            "status": status_from(text),
            "guide_price": guide,
            "sale_price": sold,
            "annual_rent": annual_rent,
            "tenure": tenure,
            "property_type": title[:180] if title else None,
            "image_url": image,
            "description": text[:6500],
            "captured_at": now_iso(),
        }
    except Exception as exc:
        return {"_error": f"{type(exc).__name__}: {exc}", "url": url}


def load_json(path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def main(batch_size=2):
    discovery = load_json(DISCOVERY, {})
    auctions = discovery.get("auctions") or []
    progress = load_json(PROGRESS, {"schema_version": 1, "sources": {}})
    state = progress.setdefault("sources", {}).setdefault("Allsop Commercial", {})
    completed = set(state.get("completed_auction_ids") or [])
    lot_db = load_json(LOTS, {"schema_version": 1, "generated_at": None, "lots": []})
    existing = {x.get("url"): x for x in lot_db.get("lots", []) if x.get("url")}

    selected = [a for a in auctions if a.get("auction_id") not in completed][:batch_size]
    state.update({
        "status": "RUNNING" if selected else "CAUGHT UP",
        "auctions_discovered": len(auctions),
        "auctions_completed": len(completed),
        "lots_captured": len(existing),
        "last_run_started": now_iso(),
    })
    progress["updated_at"] = now_iso()
    save(PROGRESS, progress)

    failures = state.setdefault("failures", [])
    for auction in selected:
        auction_id = auction.get("auction_id")
        try:
            links, discovery_method = lot_links(auction["results_url"])
            if not links:
                raise RuntimeError("No lot-overview links found after requests and browser rendering")
            rows = []
            with ThreadPoolExecutor(max_workers=8) as pool:
                futs = {pool.submit(hydrate, url, auction): url for url in links}
                for fut in as_completed(futs):
                    rows.append(fut.result())
            good = [r for r in rows if not r.get("_error") and r.get("address")]
            bad = [r for r in rows if r.get("_error")]
            if not good:
                raise RuntimeError(f"Hydration produced 0 valid lots from {len(links)} links; errors={len(bad)}")
            for row in good:
                existing[row["url"]] = row
            if bad:
                failures.append({
                    "auction_id": auction_id,
                    "label": auction.get("label"),
                    "error": f"{len(bad)} of {len(rows)} lot pages failed hydration",
                    "samples": bad[:8],
                    "at": now_iso(),
                })
            completed.add(auction_id)
            state["completed_auction_ids"] = sorted(completed)
            state["auctions_completed"] = len(completed)
            state["lots_captured"] = len(existing)
            state["last_result_page_method"] = discovery_method
            state["earliest_month_reached"] = min(
                [a.get("month") for a in auctions if a.get("auction_id") in completed and a.get("month")],
                default=None,
            )
            state["last_success"] = now_iso()
            lot_db["lots"] = sorted(existing.values(), key=lambda x: (x.get("auction_date") or "", x.get("lot_number") or ""), reverse=True)
            lot_db["generated_at"] = now_iso()
            save(LOTS, lot_db)
            progress["updated_at"] = now_iso()
            save(PROGRESS, progress)
        except Exception as exc:
            failures.append({
                "auction_id": auction_id,
                "label": auction.get("label"),
                "error": f"{type(exc).__name__}: {exc}",
                "at": now_iso(),
            })
            state["status"] = "DEGRADED"
            progress["updated_at"] = now_iso()
            save(PROGRESS, progress)

    remaining = [a for a in auctions if a.get("auction_id") not in completed]
    state["status"] = "CAUGHT UP" if not remaining else "RUNNING"
    state["remaining_auctions"] = len(remaining)
    state["last_run_completed"] = now_iso()
    progress["updated_at"] = now_iso()
    save(PROGRESS, progress)
    lot_db["lots"] = sorted(existing.values(), key=lambda x: (x.get("auction_date") or "", x.get("lot_number") or ""), reverse=True)
    lot_db["generated_at"] = now_iso()
    save(LOTS, lot_db)
    print(json.dumps({
        "status": state["status"],
        "auctions_discovered": len(auctions),
        "auctions_completed": len(completed),
        "remaining_auctions": len(remaining),
        "lots_captured": len(existing),
        "failures": len(failures),
    }, indent=2))


if __name__ == "__main__":
    main()

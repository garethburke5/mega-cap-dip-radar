from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urljoin

from playwright.sync_api import sync_playwright

OUT = Path("auction_history_output")
DISCOVERY = OUT / "allsop_discovery.json"
DIAG = OUT / "allsop_result_page_diagnostic.json"


def main():
    discovery = json.loads(DISCOVERY.read_text(encoding="utf-8"))
    auctions = (discovery.get("auctions") or [])[:2]
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for auction in auctions:
            page = browser.new_page(
                user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131 Safari/537.36"
            )
            network = []
            def on_response(resp):
                ct = (resp.headers or {}).get("content-type", "")
                u = resp.url
                if any(k in u.lower() for k in ("api", "search", "auction", "property", "lot")) or "json" in ct.lower():
                    network.append({"status": resp.status, "url": u, "content_type": ct})
            page.on("response", on_response)
            response = page.goto(auction["results_url"], wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(7000)
            hrefs = page.eval_on_selector_all("a", "els => els.map(e => e.href).filter(Boolean)")
            lot_hrefs = [h.split("?",1)[0] for h in hrefs if "/lot-overview/" in h]
            buttons = page.eval_on_selector_all("button", "els => els.map(e => (e.innerText || e.textContent || '').trim()).filter(Boolean)")
            inputs = page.eval_on_selector_all("input", "els => els.map(e => ({name:e.name,type:e.type,value:e.value,placeholder:e.placeholder}))")
            body = page.locator("body").inner_text(timeout=10000)
            results.append({
                "auction_id": auction.get("auction_id"),
                "label": auction.get("label"),
                "requested_url": auction.get("results_url"),
                "final_url": page.url,
                "status": response.status if response else None,
                "title": page.title(),
                "lot_href_count": len(set(lot_hrefs)),
                "lot_hrefs": list(dict.fromkeys(lot_hrefs))[:30],
                "all_href_count": len(hrefs),
                "sample_hrefs": hrefs[:80],
                "buttons": buttons[:50],
                "inputs": inputs[:50],
                "body_text": body[:6000],
                "network": network[-120:],
            })
            page.close()
        browser.close()
    DIAG.write_text(json.dumps({"results": results}, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"diagnosed": len(results), "lot_counts": [x["lot_href_count"] for x in results]}, indent=2))


if __name__ == "__main__":
    main()

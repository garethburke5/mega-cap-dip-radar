from __future__ import annotations

from playwright.sync_api import sync_playwright

from auction_history_runner import backfill_auction_house as base

_plain_get = base.get


def browser_get(url):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1600})
        page.goto(url, wait_until='domcontentloaded', timeout=45000)
        try:
            page.wait_for_load_state('networkidle', timeout=12000)
        except Exception:
            pass
        # Archive results are injected after DOMContentLoaded on the shared frontend.
        if '/auction/past-auctions' in url:
            try:
                page.wait_for_selector('a[href*="/auction/lot/"]', timeout=12000)
            except Exception:
                pass
        html = page.content()
        browser.close()
        return html


def smart_get(url, timeout=35):
    html = _plain_get(url, timeout=timeout)
    if '/auction/past-auctions' in url and '/auction/lot/' not in html:
        return browser_get(url)
    return html


def main(batch_pages=4):
    base.get = smart_get
    return base.main(batch_pages=batch_pages)


if __name__ == '__main__':
    main()

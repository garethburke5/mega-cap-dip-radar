from __future__ import annotations

import re

from . import backfill_strettons as base

ARCHIVES = (
    'https://www.strettons.co.uk/auctions/past-auctions/',
    'https://residential.strettons.co.uk/auctions/past-auctions/',
)
# Independently indexed Strettons result pages used only as bootstrap anchors
# when the archive landing page is client-rendered. Every anchor is re-fetched
# and validated before any lot is accepted.
BOOTSTRAP_IDS = ('3608', '3606', '2766')
DETAIL_RE = re.compile(r'/auctions/past-auctions/past-auction-details/(\d+)/?', re.I)
_HTTP_GET = base.get
_RENDER_CACHE = {}


def _looks_useful(url, html):
    if not html:
        return False
    if 'past-auction-details/' in html:
        return True
    if '/past-auction-details/' in url:
        text = base.clean(base.BeautifulSoup(html, 'html.parser').get_text(' ', strip=True))
        return bool(base.POSTCODE.search(text) and re.search(r'\bLot\s+\d+', text, re.I))
    return False


def _rendered_get(url):
    if url in _RENDER_CACHE:
        return _RENDER_CACHE[url]
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(
            viewport={'width': 1440, 'height': 1400},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/140 Safari/537.36',
        )
        page.goto(url, wait_until='domcontentloaded', timeout=60000)
        page.wait_for_timeout(1600)
        html = page.content()
        browser.close()
    _RENDER_CACHE[url] = html
    return html


def smart_get(url, timeout=35):
    try:
        html = _HTTP_GET(url, timeout=timeout)
        if _looks_useful(url, html):
            return html
    except Exception:
        html = None
    # Strettons' archive/result content is sometimes injected after initial
    # document load. Browser rendering is a source-specific fallback only.
    try:
        rendered = _rendered_get(url)
        return rendered or html or ''
    except Exception:
        if html is not None:
            return html
        raise


def _validated_event(eid, url):
    html = smart_get(url)
    text = base.clean(base.BeautifulSoup(html, 'html.parser').get_text(' ', strip=True))
    if 'Past Auctions' not in text or not base.POSTCODE.search(text) or not re.search(r'\bLot\s+\d+', text, re.I):
        return None
    return {
        'auction_id': str(eid),
        'url': url,
        'label': text[:500],
        'auction_date': base.parse_date(text),
    }


def discover_events(max_pages=24):
    events = {}
    pages_seen = []
    failures = []

    for archive in ARCHIVES:
        try:
            html = smart_get(archive)
            pages_seen.append(archive)
            for eid in sorted(set(DETAIL_RE.findall(html))):
                url = f'https://www.strettons.co.uk/auctions/past-auctions/past-auction-details/{eid}/'
                try:
                    ev = _validated_event(eid, url)
                    if ev:
                        events[str(eid)] = ev
                except Exception as exc:
                    failures.append({'auction_id': str(eid), 'url': url, 'error': repr(exc)})
        except Exception as exc:
            failures.append({'auction_id': None, 'url': archive, 'error': repr(exc)})

    for eid in BOOTSTRAP_IDS:
        if eid in events:
            continue
        url = f'https://www.strettons.co.uk/auctions/past-auctions/past-auction-details/{eid}/'
        try:
            ev = _validated_event(eid, url)
            if ev:
                events[eid] = ev
        except Exception as exc:
            failures.append({'auction_id': eid, 'url': url, 'error': repr(exc)})

    rows = list(events.values())
    rows.sort(key=lambda x: (x.get('auction_date') or '', int(x.get('auction_id') or 0)), reverse=True)
    discovery = {
        'archive_pages_seen': len(pages_seen),
        'terminal_page_seen': False,
        'archive_urls_seen': pages_seen,
        'bootstrap_anchor_count': len(BOOTSTRAP_IDS),
        'validated_events': len(rows),
        'discovery_failures': failures[-20:],
        'strategy': 'plain HTTP where complete; Playwright render fallback; validated result-page bootstrap',
    }
    return rows, discovery


def main(batch_size=8):
    original_discover = base.discover_events
    original_get = base.get
    base.discover_events = discover_events
    base.get = smart_get
    try:
        return base.main(batch_size)
    finally:
        base.discover_events = original_discover
        base.get = original_get


if __name__ == '__main__':
    main()

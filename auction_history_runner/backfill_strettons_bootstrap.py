from __future__ import annotations

import re
from urllib.parse import urljoin

from . import backfill_strettons as base

ARCHIVES = (
    'https://www.strettons.co.uk/auctions/past-auctions/',
    'https://residential.strettons.co.uk/auctions/past-auctions/',
)
# Search-indexed Strettons result pages used only as bootstrap anchors when the
# archive landing page is client-rendered to plain HTTP clients. Each anchor is
# validated by fetching the page and requiring a dated Past Auctions heading +
# at least one postcode-bearing lot before it is admitted to the crawl.
BOOTSTRAP_IDS = ('3608', '3606', '2766')
DETAIL_RE = re.compile(r'/auctions/past-auctions/past-auction-details/(\d+)/?', re.I)


def _validated_event(eid, url):
    html = base.get(url)
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

    # First try both public archive host variants. Extract detail IDs from raw
    # HTML as well as anchors because Strettons has used JS/data attributes.
    for archive in ARCHIVES:
        try:
            html = base.get(archive)
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

    # If the landing pages expose no detail URLs, bootstrap from independently
    # indexed Strettons result pages. These are not trusted blindly: every page
    # is re-fetched and validated above before use.
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
        'strategy': 'dual-host raw HTML extraction + validated indexed result-page anchors',
    }
    return rows, discovery


def main(batch_size=8):
    original = base.discover_events
    base.discover_events = discover_events
    try:
        return base.main(batch_size)
    finally:
        base.discover_events = original


if __name__ == '__main__':
    main()

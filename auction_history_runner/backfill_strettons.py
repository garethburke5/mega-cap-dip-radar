from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

BASE = 'https://www.strettons.co.uk'
ARCHIVE = BASE + '/auctions/past-auctions/'
OUT = Path('auction_history_output')
LOTS_FILE = OUT / 'strettons_lots.json'
PROGRESS_FILE = OUT / 'progress.json'
UA = {'User-Agent': 'AuctionSniper-History/2.0 (+public historical research)'}
POSTCODE = re.compile(r'\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b', re.I)
EVENT_PATH = re.compile(r'^/auctions/past-auctions/past-auction-details/(\d+)/?$', re.I)
POSITIVE_COMMERCIAL = re.compile(r'\b(commercial|shop|retail|office|industrial|warehouse|investment|mixed[- ]?use|public house|restaurant|cafe|takeaway|development site|business premises|showroom|garage|workshop)\b', re.I)
RESIDENTIAL = re.compile(r'\b(flat|maisonette|house|bungalow|apartment|dwelling)\b', re.I)


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def clean(v):
    return re.sub(r'\s+', ' ', str(v or '')).strip()


def get(url, timeout=35):
    r = requests.get(url, headers=UA, timeout=timeout)
    r.raise_for_status()
    return r.text


def load_json(path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return default


def save_json(path, payload, compact=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, separators=(',', ':') if compact else None, indent=None if compact else 2), encoding='utf-8')


def event_id(url):
    m = EVENT_PATH.match(urlparse(url).path)
    return m.group(1) if m else url.rstrip('/').rsplit('/', 1)[-1]


def parse_date(text):
    for pat in (
        r'Past Auctions?\s*[-–—:]?\s*(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s*(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)\s+(20\d{2})',
        r'(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s*(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)\s+(20\d{2})',
        r'\b(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)\s+(20\d{2})\b',
    ):
        m = re.search(pat, text, re.I)
        if not m:
            continue
        try:
            return datetime.strptime(' '.join(m.groups()), '%d %B %Y').date().isoformat()
        except Exception:
            pass
    return None


def discover_events(max_pages=24):
    """Discover archive events without pretending a finite snapshot is complete.

    Strettons' archive has changed layout over time. We walk archive pagination
    when present and also harvest past-auction-detail links from every page. The
    caller keeps status BACKFILLING unless the archive itself exposes a terminal
    pagination boundary, so zero/partial discovery can never be marked complete.
    """
    events = {}
    pages_seen = set()
    queue = [ARCHIVE]
    terminal_page_seen = False
    while queue and len(pages_seen) < max_pages:
        page_url = queue.pop(0)
        if page_url in pages_seen:
            continue
        pages_seen.add(page_url)
        html = get(page_url)
        soup = BeautifulSoup(html, 'html.parser')
        new_event_count = 0
        for a in soup.find_all('a', href=True):
            full = urljoin(BASE, a.get('href') or '').split('#')[0]
            path = urlparse(full).path
            m = EVENT_PATH.match(path)
            if m:
                eid = m.group(1)
                if eid not in events:
                    block = clean(a.get_text(' ', strip=True))
                    for parent in a.parents:
                        txt = clean(parent.get_text(' ', strip=True))
                        if len(txt) < 1400 and re.search(r'20\d{2}', txt):
                            block = txt
                            break
                    events[eid] = {'auction_id': eid, 'url': full, 'label': block, 'auction_date': parse_date(block)}
                    new_event_count += 1
                continue
            low = path.lower()
            if '/auctions/past-auctions/' in low and re.search(r'(?:page[/=-]?\d+|paged=\d+)', full, re.I):
                if full not in pages_seen and full not in queue:
                    queue.append(full)
        # Some archive templates simply stop exposing a next-page control.
        next_link = soup.find('a', string=re.compile(r'^\s*(?:next|older)\b', re.I))
        if next_link and next_link.get('href'):
            nxt = urljoin(BASE, next_link.get('href'))
            if nxt not in pages_seen and nxt not in queue:
                queue.append(nxt)
        elif page_url != ARCHIVE and new_event_count == 0:
            terminal_page_seen = True
    rows = list(events.values())
    rows.sort(key=lambda x: (x.get('auction_date') or '', int(x.get('auction_id') or 0)), reverse=True)
    return rows, {'archive_pages_seen': len(pages_seen), 'terminal_page_seen': terminal_page_seen, 'archive_urls_seen': sorted(pages_seen)}


def nearest_lot_block(node):
    chosen = node.parent or node
    for parent in node.parents:
        txt = clean(parent.get_text(' ', strip=True))
        if re.search(r'\bLot\s+\d+[A-Z]?\b', txt, re.I) and len(txt) < 7000:
            chosen = parent
            if POSTCODE.search(txt) and re.search(r'\b(?:Sold|Withdrawn|Guide Price|Unsold|Available)\b', txt, re.I):
                break
    return chosen


def lot_nodes(soup):
    found = []
    seen = set()
    for tag in soup.find_all(['h2','h3','h4','h5','h6','a','strong']):
        txt = clean(tag.get_text(' ', strip=True))
        m = re.search(r'\bLot\s+(\d+[A-Z]?)\b', txt, re.I)
        if not m or not POSTCODE.search(txt):
            continue
        key = m.group(1).upper()
        if key in seen:
            continue
        seen.add(key)
        found.append((key, tag))
    return found


def price(pattern, text):
    m = re.search(pattern, text, re.I)
    return float(m.group(1).replace(',', '')) if m else None


def status_of(text):
    if re.search(r'\bsold\s+prior\b', text, re.I): return 'Sold Prior'
    if re.search(r'\bwithdrawn\b', text, re.I): return 'Withdrawn'
    if re.search(r'\bsold\b', text, re.I): return 'Sold'
    if re.search(r'\bunsold\b', text, re.I): return 'Unsold'
    if re.search(r'\bavailable\b', text, re.I): return 'Available'
    return None


def is_commercial(text):
    if POSITIVE_COMMERCIAL.search(text):
        return True
    # Strettons often classifies commercial investments as "other". Preserve
    # those where rental/investment language proves non-owner-occupier intent.
    if re.search(r'\b(other|ground rent|let to|rental income|per annum|p\.a\.)\b', text, re.I) and not RESIDENTIAL.search(text):
        return True
    return False


def exact_listing_url(block, event_url):
    for a in block.find_all('a', href=True):
        href = urljoin(BASE, a.get('href') or '')
        low = urlparse(href).path.lower()
        if 'auction-commercial-property-for-sale' in low or 'auction-mixed-use-property-for-sale' in low:
            return href.split('#')[0]
    return event_url


def crawl_event(event):
    html = get(event['url'])
    soup = BeautifulSoup(html, 'html.parser')
    page_text = clean(soup.get_text(' ', strip=True))
    auction_date = parse_date(page_text) or event.get('auction_date')
    rows = []
    candidates = lot_nodes(soup)
    for lot_no, node in candidates:
        block_node = nearest_lot_block(node)
        block = clean(block_node.get_text(' ', strip=True))
        if not is_commercial(block):
            continue
        heading = clean(node.get_text(' ', strip=True))
        pm = POSTCODE.search(heading)
        address = heading
        if pm:
            address = heading[:pm.end()]
        address = re.sub(r'^.*?\bLot\s+\d+[A-Z]?\s*[-–—:]?\s*', '', address, flags=re.I).strip(' -–—:')
        if not POSTCODE.search(address):
            continue
        sale = price(r'Sold(?:\s+(?:for|at))?\s*£\s*([\d,]+(?:\.\d+)?)', block)
        guide = price(r'Guide(?:\s+Price)?\s*£\s*([\d,]+(?:\.\d+)?)', block)
        rent = None
        for pat in (
            r'(?:rent(?:al)?(?: income)?|producing|let at|income)[^£]{0,70}£\s*([\d,]+(?:\.\d+)?)\s*(?:p\.?a\.?|per annum|pa)',
            r'£\s*([\d,]+(?:\.\d+)?)\s*(?:p\.?a\.?|per annum|pa)',
        ):
            rent = price(pat, block)
            if rent is not None: break
        tenure = 'Freehold' if re.search(r'\bfreehold\b', block, re.I) else ('Leasehold' if re.search(r'\b(?:long\s+)?leasehold\b', block, re.I) else None)
        listing_url = exact_listing_url(block_node, event['url'])
        source_id = f"{event['auction_id']}:{lot_no}"
        rows.append({
            'source': 'Strettons',
            'source_id': source_id,
            'auction_id': event['auction_id'],
            'auction_date': auction_date,
            'auction_month': auction_date[:7] if auction_date else None,
            'lot_number': lot_no,
            'address': address,
            'status': status_of(block),
            'guide_price': guide,
            'sale_price': sale,
            'annual_rent': rent,
            'tenure': tenure,
            'property_type': 'Commercial / mixed-use',
            'description': block[:5000],
            'url': listing_url,
            'result_page_url': event['url'],
            'auction_url': event['url'],
            'captured_at': now_iso(),
        })
    if not candidates:
        raise RuntimeError('no lot headings with postcode discovered on Strettons past-auction detail page')
    return rows, {'candidate_lots': len(candidates), 'commercial_lots': len(rows), 'auction_date': auction_date}


def merge_global_progress(source_progress):
    p = load_json(PROGRESS_FILE, {'schema_version': 1, 'updated_at': now_iso(), 'sources': {}})
    p.setdefault('sources', {})['Strettons'] = source_progress
    p['updated_at'] = now_iso()
    save_json(PROGRESS_FILE, p)


def main(batch_size=8):
    old_global = load_json(PROGRESS_FILE, {'sources': {}})
    old = (old_global.get('sources') or {}).get('Strettons') or {}
    try:
        events, discovery = discover_events()
        discovery_error = None if events else 'archive discovery returned zero past-auction events'
    except Exception as exc:
        events, discovery = [], {'archive_pages_seen': 0, 'terminal_page_seen': False}
        discovery_error = repr(exc)

    payload = load_json(LOTS_FILE, {'schema_version': 1, 'source': 'Strettons', 'lots': []})
    existing = {str(x.get('source_id')): x for x in payload.get('lots', []) if x.get('source_id')}
    completed = set(str(x) for x in old.get('completed_auction_ids', []))
    failures = [x for x in old.get('failures', []) if str(x.get('auction_id')) not in completed]
    if discovery_error:
        failures.append({'auction_id': None, 'url': ARCHIVE, 'error': discovery_error, 'at': now_iso()})
    todo = [e for e in events if str(e['auction_id']) not in completed]
    processed = 0
    last_auction = old.get('last_auction')
    for event in todo[:batch_size]:
        try:
            rows, evidence = crawl_event(event)
            # A past auction may genuinely contain no commercial lots. Completion
            # is allowed only if lot candidates were seen and classified.
            for row in rows:
                existing[str(row['source_id'])] = row
            completed.add(str(event['auction_id']))
            failures = [x for x in failures if str(x.get('auction_id')) != str(event['auction_id'])]
            last_auction = {**event, **evidence}
            processed += 1
        except Exception as exc:
            failures.append({'auction_id': event['auction_id'], 'url': event['url'], 'error': repr(exc), 'at': now_iso()})

    lots = list(existing.values())
    lots.sort(key=lambda x: ((x.get('auction_date') or ''), str(x.get('lot_number') or ''), str(x.get('source_id') or '')), reverse=True)
    save_json(LOTS_FILE, {'schema_version': 1, 'source': 'Strettons', 'generated_at': now_iso(), 'lots': lots}, compact=True)
    remaining = max(0, len(events) - len(completed)) if events else None
    # Conservative by design: archive discovery is not considered globally caught
    # up until a terminal archive boundary is proven.
    if discovery_error:
        status = 'DISCOVERY_FAILED'
    elif remaining or not discovery.get('terminal_page_seen'):
        status = 'BACKFILLING'
    elif failures:
        status = 'BACKFILLING'
    else:
        status = 'CAUGHT_UP'
    source_progress = {
        'status': status,
        'auctions_discovered': len(events),
        'auctions_completed': len(completed),
        'lots_captured': len(lots),
        'earliest_month_reached': min((x.get('auction_month') for x in lots if x.get('auction_month')), default=None),
        'latest_month_seen': max((x.get('auction_month') for x in lots if x.get('auction_month')), default=None),
        'remaining_discovered_auctions': remaining,
        'completed_auction_ids': sorted(completed),
        'failures': failures[-50:],
        'discovery': discovery,
        'ingestion_method': 'Strettons server-rendered past-auction detail pages',
        'evidence_policy': 'exact Strettons lot URL where available + exact past-auction result page',
        'last_auction': last_auction,
        'last_success': now_iso() if processed else old.get('last_success'),
        'last_run_completed': now_iso(),
    }
    merge_global_progress(source_progress)
    print(json.dumps({k: source_progress[k] for k in ('status','auctions_discovered','auctions_completed','lots_captured','remaining_discovered_auctions')}, indent=2))


if __name__ == '__main__':
    main()

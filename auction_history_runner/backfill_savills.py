from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

BASE = 'https://auctions.savills.co.uk'
ARCHIVE = BASE + '/past-auctions'
OUT = Path('auction_history_output')
LOTS_FILE = OUT / 'savills_lots.json'
PROGRESS_FILE = OUT / 'progress.json'
UA = {'User-Agent': 'AuctionSniper-History/2.0 (+public historical research)'}
POSTCODE = re.compile(r'\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b', re.I)
EVENT_PATH = re.compile(r'^/auctions/[^/?#]+-\d+/?$')
PAGE_PATH = re.compile(r'/page-(\d+)(?:/|$)')
LOT_PATH = re.compile(r'^/auctions/[^/]+-\d+/[^/?#]+-\d+/?$')
COMMERCIAL_TYPE = '253'


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def clean(v):
    return re.sub(r'\s+', ' ', str(v or '')).strip()


def path_of(href):
    try:
        return urlparse(urljoin(BASE, href or '')).path
    except Exception:
        return ''


def get(url, timeout=30):
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


def date_from_text(text):
    m = re.search(r'\b(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s+(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)\s+(20\d{2})\b', text, re.I)
    if not m:
        return None
    try:
        return datetime.strptime(f'{m.group(1)} {m.group(2)} {m.group(3)}', '%d %B %Y').date().isoformat()
    except Exception:
        return None


def event_id_from_url(url):
    m = re.search(r'-(\d+)/?$', urlparse(url).path)
    return m.group(1) if m else url.rstrip('/').rsplit('/', 1)[-1]


def discover_events():
    events = {}
    consecutive_empty = 0
    for page in range(1, 40):
        url = ARCHIVE if page == 1 else f'{ARCHIVE}/archive/page-{page}'
        html = get(url)
        soup = BeautifulSoup(html, 'html.parser')
        found = 0
        for a in soup.find_all('a', href=True):
            href = a.get('href') or ''
            path = path_of(href)
            if not EVENT_PATH.match(path):
                continue
            full = urljoin(BASE, href)
            eid = event_id_from_url(full)
            if eid in events:
                continue
            block = clean(a.get_text(' ', strip=True))
            for parent in a.parents:
                txt = clean(parent.get_text(' ', strip=True))
                if 'Offered' in txt and 'Sold' in txt and len(txt) < 1800:
                    block = txt
                    break
            offered = None
            mo = re.search(r'Offered\s+(\d+)', block, re.I)
            if mo:
                offered = int(mo.group(1))
            events[eid] = {
                'auction_id': eid,
                'label': clean(a.get_text(' ', strip=True)),
                'url': full,
                'auction_date': date_from_text(block),
                'offered_hint': offered,
            }
            found += 1
        if found == 0:
            consecutive_empty += 1
        else:
            consecutive_empty = 0
        if page > 1 and consecutive_empty >= 2:
            break
    rows = list(events.values())
    rows.sort(key=lambda x: (x.get('auction_date') or '', x.get('auction_id') or ''), reverse=True)
    return rows


def commercial_catalogue_url(event_url, page=1):
    # Savills' default catalogue can be hydrated client-side for non-browser HTTP
    # clients. The explicit commercial filter + quantity route is server-rendered
    # and contains the exact lot anchors/results required by the history runner.
    return event_url.rstrip('/') + f'/page-{page}/quantity-100/property_type-{COMMERCIAL_TYPE}/sort-by-0'


def max_pages(html):
    soup = BeautifulSoup(html, 'html.parser')
    pages = [1]
    for a in soup.find_all('a', href=True):
        m = PAGE_PATH.search(path_of(a.get('href')))
        if m:
            pages.append(int(m.group(1)))
    return max(pages)


def nearest_lot_block(anchor):
    chosen = anchor.parent
    for parent in anchor.parents:
        txt = clean(parent.get_text(' ', strip=True))
        if re.search(r'\bLot\s+[\w.-]+\b', txt, re.I) and len(txt) < 5000:
            chosen = parent
            if re.search(r'\b(?:Hammer Price|Sold|Withdrawn|Available at|Guide Price)\b', txt, re.I):
                break
    return chosen


def parse_status(block):
    for label in ('Sold Prior', 'Sold Post', 'Withdrawn Prior', 'Withdrawn', 'Sold', 'Unsold', 'Postponed', 'Available'):
        if re.search(rf'\b{re.escape(label)}\b', block, re.I):
            return label
    return None


def parse_page(event, page_url, html):
    soup = BeautifulSoup(html, 'html.parser')
    rows, seen = [], set()
    event_prefix = urlparse(event['url']).path.rstrip('/') + '/'
    for a in soup.find_all('a', href=True):
        href = a.get('href') or ''
        path = path_of(href)
        if not path.startswith(event_prefix) or not LOT_PATH.match(path):
            continue
        full = urljoin(BASE, href)
        if full in seen:
            continue
        address = clean(a.get_text(' ', strip=True))
        if len(address) < 5 or not POSTCODE.search(address):
            continue
        seen.add(full)
        block_node = nearest_lot_block(a)
        block = clean(block_node.get_text(' ', strip=True))
        lm = re.search(r'\bLot\s+([\w.-]+)\b', block, re.I)
        lot_no = lm.group(1) if lm else None
        hammer = None
        hm = re.search(r'Hammer\s+Price\s*£\s*([\d,]+(?:\.\d+)?)', block, re.I)
        if hm:
            hammer = float(hm.group(1).replace(',', ''))
        guide = None
        gm = re.search(r'Guide(?:\s+Price)?\s*£\s*([\d,]+(?:\.\d+)?)', block, re.I)
        if gm:
            guide = float(gm.group(1).replace(',', ''))
        available = None
        am = re.search(r'Available\s+at\s*£\s*([\d,]+(?:\.\d+)?)', block, re.I)
        if am:
            available = float(am.group(1).replace(',', ''))
        rent = None
        for pat in (
            r'(?:producing|rent(?:al)?(?: income)?|let at|investment let at)[^£]{0,60}£\s*([\d,]+(?:\.\d+)?)\s*(?:p\.?a\.?|per annum|pa)',
            r'£\s*([\d,]+(?:\.\d+)?)\s*(?:p\.?a\.?|per annum|pa)',
        ):
            rm = re.search(pat, block, re.I)
            if rm:
                rent = float(rm.group(1).replace(',', ''))
                break
        tenure = None
        if re.search(r'\bfreehold\b', block, re.I):
            tenure = 'Freehold'
        elif re.search(r'\b(?:long\s+)?leasehold\b|\byear lease\b', block, re.I):
            tenure = 'Leasehold'
        sid = re.search(r'-(\d+)/?$', path)
        rows.append({
            'source': 'Savills',
            'source_id': sid.group(1) if sid else full.rstrip('/').rsplit('/', 1)[-1],
            'auction_id': event['auction_id'],
            'auction_date': event.get('auction_date'),
            'auction_month': (event.get('auction_date') or '')[:7] or None,
            'lot_number': lot_no,
            'address': address,
            'status': parse_status(block),
            'guide_price': guide,
            'sale_price': hammer,
            'available_price': available,
            'annual_rent': rent,
            'tenure': tenure,
            'features': [clean(x.get_text(' ', strip=True)) for x in block_node.find_all('li') if clean(x.get_text(' ', strip=True))][:30],
            'url': full,
            'result_page_url': page_url,
            'auction_url': event['url'],
            'captured_at': now_iso(),
        })
    return rows


def crawl_event(event):
    first_url = commercial_catalogue_url(event['url'], 1)
    first_html = get(first_url)
    pages = max_pages(first_html)
    collected, page_shapes = [], []
    for page in range(1, pages + 1):
        url = commercial_catalogue_url(event['url'], page)
        html = first_html if page == 1 else get(url)
        rows = parse_page(event, url, html)
        collected.extend(rows)
        page_shapes.append({'page': page, 'rows': len(rows), 'url': url})
    dedup = {row['source_id']: row for row in collected}
    rows = list(dedup.values())
    return rows, {
        'pages': pages,
        'page_shapes': page_shapes,
        'unique_rows': len(rows),
        'offered_hint': event.get('offered_hint'),
        'catalogue_filter': f'property_type-{COMMERCIAL_TYPE}',
    }


def merge_global_progress(source_progress):
    p = load_json(PROGRESS_FILE, {'schema_version': 1, 'updated_at': now_iso(), 'sources': {}})
    p.setdefault('sources', {})['Savills'] = source_progress
    p['updated_at'] = now_iso()
    save_json(PROGRESS_FILE, p)


def main(batch_size=4):
    old_global = load_json(PROGRESS_FILE, {'sources': {}})
    old = (old_global.get('sources') or {}).get('Savills') or {}
    try:
        events = discover_events()
        discovery_error = None if events else 'archive discovery returned zero auction events'
    except Exception as exc:
        events = []
        discovery_error = repr(exc)

    lot_payload = load_json(LOTS_FILE, {'schema_version': 1, 'source': 'Savills', 'lots': []})
    existing = {str(x.get('source_id')): x for x in lot_payload.get('lots', []) if x.get('source_id')}
    completed = set(str(x) for x in old.get('completed_auction_ids', []))
    failures = [x for x in old.get('failures', []) if x.get('auction_id') not in completed]
    if discovery_error:
        failures.append({'auction_id': None, 'url': ARCHIVE, 'error': discovery_error, 'at': now_iso()})
    todo = [e for e in events if str(e['auction_id']) not in completed]
    processed = 0
    last_auction = old.get('last_auction')
    for event in todo[:batch_size]:
        try:
            rows, evidence = crawl_event(event)
            if not rows:
                raise RuntimeError('no commercial property rows captured from explicit Savills commercial catalogue route')
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
    save_json(LOTS_FILE, {'schema_version': 1, 'source': 'Savills', 'generated_at': now_iso(), 'lots': lots}, compact=True)
    dates = [e.get('auction_date') for e in events if e.get('auction_date')]
    remaining = max(0, len(events) - len(completed)) if events else None
    if discovery_error:
        status = 'DISCOVERY_FAILED'
    elif remaining == 0 and not failures:
        status = 'CAUGHT_UP'
    else:
        status = 'BACKFILLING'
    source_progress = {
        'status': status,
        'auctions_discovered': len(events),
        'auctions_completed': len(completed),
        'lots_captured': len(lots),
        'earliest_month_reached': min((x.get('auction_month') for x in lots if x.get('auction_month')), default=None),
        'latest_month_seen': max((d[:7] for d in dates), default=None),
        'remaining_auctions': remaining,
        'completed_auction_ids': sorted(completed),
        'failures': failures[-50:],
        'ingestion_method': f'Savills server-rendered commercial catalogue filter property_type-{COMMERCIAL_TYPE}',
        'last_auction': last_auction,
        'last_success': now_iso() if processed else old.get('last_success'),
        'last_run_completed': now_iso(),
        'evidence_policy': 'exact lot URL + auction page + exact filtered commercial catalogue result page',
    }
    merge_global_progress(source_progress)
    print(json.dumps({k: source_progress[k] for k in ('status','auctions_discovered','auctions_completed','lots_captured','remaining_auctions')}, indent=2))


if __name__ == '__main__':
    main()

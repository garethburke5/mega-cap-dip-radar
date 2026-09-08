from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse, parse_qs

import requests
from bs4 import BeautifulSoup

OUT = Path('auction_history_output')
PROGRESS = OUT / 'progress.json'
LOTS = OUT / 'auction_house_lots.json'
BASE = 'https://www.auctionhouse.co.uk'
POSTCODE = re.compile(r'\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b', re.I)
LOT_PATH = re.compile(r'/([^/]+)/auction/lot/(\d+)/?$', re.I)
REGIONS = (
    ('westyorkshire', 'Auction House West Yorkshire'),
    ('eastanglia', 'Auction House East Anglia'),
    ('sussexandhampshire', 'Auction House Sussex & Hampshire'),
    ('southwest', 'Auction House South West'),
    ('wales', 'Auction House Wales'),
    ('cumbria', 'Auction House Cumbria'),
    ('northeast', 'Auction House North East'),
    ('northwest', 'Auction House North West'),
    ('lincolnshire', 'Auction House Lincolnshire, North Notts & South Yorks'),
    ('manchester', 'Auction House Manchester'),
    ('chesterfieldandnorthderbyshire', 'Auction House Chesterfield & North Derbyshire'),
    ('coventryandwarwickshire', 'Auction House Coventry & Warwickshire'),
    ('scotland', 'Auction House Scotland'),
    ('hullandeastyorkshire', 'Auction House Hull & East Yorkshire'),
    ('birmingham', 'Auction House Birmingham & Black Country'),
    ('northantsbedsandbucks', 'Auction House Northants, Beds & Bucks'),
    ('leicestershire', 'Auction House Leicestershire'),
    ('teesvalley', 'Auction House North Yorkshire & Tees Valley'),
    ('national', 'Auction House National Online'),
)
COMMERCIAL = re.compile(
    r'\b(?:commercial|mixed[- ]use|shop|retail|office|warehouse|industrial|workshop|'
    r'restaurant|takeaway|public house|\bpub\b|hotel|business premises|commercial unit|'
    r'development site|garage block|investment property)\b', re.I)
RESIDENTIAL_ONLY = re.compile(
    r'\b(?:terraced house|semi[- ]detached house|detached house|bungalow|apartment|maisonette|flat)\b', re.I)

S = requests.Session()
S.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/140 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml',
})


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def clean(v):
    return re.sub(r'\s+', ' ', str(v or '')).strip()


def get(url, timeout=35):
    r = S.get(url, timeout=timeout)
    r.raise_for_status()
    return r.text


def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return default


def save_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding='utf-8')


def money(text):
    if not text:
        return None
    m = re.search(r'£\s*([\d,]+(?:\.\d+)?)', text)
    if not m:
        return None
    try:
        return float(m.group(1).replace(',', ''))
    except ValueError:
        return None


def result_fields(text):
    t = clean(text)
    low = t.lower()
    sale = None
    m = re.search(r'Sold\s+for\s*:\s*£\s*([\d,]+(?:\.\d+)?)', t, re.I)
    if m:
        sale = float(m.group(1).replace(',', ''))
        return 'SOLD', sale
    if 'sold prior' in low:
        return 'SOLD PRIOR', None
    if 'sold after' in low:
        return 'SOLD AFTER', None
    if 'withdrawn' in low:
        return 'WITHDRAWN', None
    if 'postponed' in low:
        return 'POSTPONED', None
    if 'no bids' in low or 'last bid' in low:
        return 'UNSOLD', None
    return 'ARCHIVED', None


def parse_date(text):
    m = re.search(r'\b(\d{1,2})/(\d{1,2})/(20\d{2})\b', text or '')
    if m:
        try:
            return datetime(int(m.group(3)), int(m.group(2)), int(m.group(1))).date().isoformat()
        except ValueError:
            pass
    m = re.search(r'\b(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)\s+(20\d{2})\b', text or '', re.I)
    if m:
        try:
            return datetime.strptime(f'{m.group(1)} {m.group(2)} {m.group(3)}', '%d %B %Y').date().isoformat()
        except ValueError:
            pass
    return None


def exact_lot_links(html, slug, page_url):
    soup = BeautifulSoup(html, 'html.parser')
    rows = []
    seen = set()
    for a in soup.find_all('a', href=True):
        href = urljoin(page_url, a.get('href')).split('#')[0]
        path = urlparse(href).path.rstrip('/')
        m = LOT_PATH.search(path)
        if not m or m.group(1).lower() != slug.lower():
            continue
        source_id = m.group(2)
        if source_id in seen:
            continue
        seen.add(source_id)
        node = a
        card = clean(a.get_text(' ', strip=True))
        for _ in range(6):
            node = getattr(node, 'parent', None)
            if node is None:
                break
            text = clean(node.get_text(' ', strip=True))
            if 20 <= len(text) <= 2200:
                card = text
                if POSTCODE.search(text) and ('Sold' in text or 'Guide' in text or 'Withdrawn' in text or 'Postponed' in text):
                    break
            if len(text) > 2200:
                break
        rows.append({'source_id': source_id, 'url': href, 'card': card})
    return rows


def parse_detail(item, source, archive_url):
    html = get(item['url'])
    soup = BeautifulSoup(html, 'html.parser')
    root = soup.find('main') or soup
    text = clean(root.get_text(' ', strip=True))
    h1 = soup.find('h1')
    address = clean(h1.get_text(' ', strip=True)) if h1 else ''
    address = re.sub(r'^Lot\s+\d+[A-Z]?\s*[:|\-]?\s*', '', address, flags=re.I)
    if not POSTCODE.search(address):
        pm = POSTCODE.search(text)
        if pm:
            prefix = text[:pm.end()]
            # Prefer the text immediately preceding the postcode, bounded by common page labels.
            prefix = re.split(r'(?:Save Lot List|Previous Lot|Next Lot|Guide\s*\|)', prefix, flags=re.I)[-1]
            address = clean(prefix[-280:])
    combined = clean(item.get('card', '') + ' ' + text)
    commercial = bool(COMMERCIAL.search(combined))
    if not commercial:
        return None
    # Do not reject mixed assets simply because a residential word is also present.
    if not address or len(address) < 6:
        return None
    status, sale_price = result_fields(item.get('card', '') + ' ' + text[:1800])
    guide = None
    gm = re.search(r'(?:Guide\s*(?:\||Price)?[^£]{0,20})£\s*([\d,]+)', combined, re.I)
    if gm:
        guide = float(gm.group(1).replace(',', ''))
    auction_date = parse_date(item.get('card', '')) or parse_date(text)
    lot_number = None
    lm = re.search(r'\bLot\s+(\d+[A-Z]?)\b', combined, re.I)
    if lm:
        lot_number = f'Lot {lm.group(1)}'
    image_url = None
    og = soup.find('meta', attrs={'property': 'og:image'})
    if og and og.get('content'):
        image_url = urljoin(item['url'], og.get('content'))
    property_type = 'Mixed Use' if re.search(r'mixed[- ]use', combined, re.I) else 'Commercial'
    if re.search(r'\b(?:retail|shop)\b', combined, re.I): property_type = 'Retail'
    elif re.search(r'\b(?:industrial|warehouse|workshop)\b', combined, re.I): property_type = 'Industrial / Warehouse'
    elif re.search(r'\boffices?\b', combined, re.I): property_type = 'Office'
    elif re.search(r'\b(?:hotel|public house|pub|restaurant|hospitality)\b', combined, re.I): property_type = 'Leisure / Hospitality'
    rent = None
    rm = re.search(r'(?:rent|income|producing)[^£]{0,55}£\s*([\d,]+(?:\.\d+)?)\s*(?:p\.?a\.?|per annum|pa)', combined, re.I)
    if rm:
        rent = float(rm.group(1).replace(',', ''))
    tenure = 'Freehold' if re.search(r'\bfreehold\b', combined, re.I) else ('Leasehold' if re.search(r'\bleasehold\b', combined, re.I) else None)
    return {
        'source': source,
        'source_id': item['source_id'],
        'url': item['url'],
        'result_page_url': archive_url,
        'auction_url': archive_url,
        'evidence_url': item['url'],
        'address': address,
        'auction_date': auction_date,
        'auction_month': auction_date[:7] if auction_date else None,
        'lot_number': lot_number,
        'status': status,
        'guide_price': guide,
        'sale_price': sale_price,
        'annual_rent': rent,
        'tenure': tenure,
        'property_type': property_type,
        'description': text[:7000],
        'image_url': image_url,
        'captured_at': now_iso(),
    }


def main(batch_pages=4):
    OUT.mkdir(parents=True, exist_ok=True)
    progress = load_json(PROGRESS, {'schema_version': 1, 'updated_at': None, 'sources': {}})
    sources = progress.setdefault('sources', {})
    state = sources.setdefault('Auction House Shared Platform', {
        'status': 'NOT_STARTED', 'pages_completed': [], 'lots_captured': 0, 'failures': [],
        'regions_completed': [], 'ingestion_method': 'Auction House /auction/past-auctions exact lot pages',
    })
    payload = load_json(LOTS, {'schema_version': 1, 'lots': []})
    existing = {str(x.get('source_id')): x for x in payload.get('lots', []) if x.get('source_id')}
    completed = set(state.get('pages_completed') or [])
    work = []
    for slug, label in REGIONS:
        for page in range(1, 121):
            key = f'{slug}:{page}'
            if key not in completed:
                work.append((slug, label, page, key))
                break
        if len(work) >= batch_pages:
            break
    state['status'] = 'RUNNING'
    state['last_run_started'] = now_iso()
    progress['updated_at'] = now_iso()
    save_json(PROGRESS, progress)
    added = 0
    failures_this_run = 0
    for slug, label, page, key in work:
        archive_url = f'{BASE}/{slug}/auction/past-auctions' + (f'?page={page}' if page > 1 else '')
        try:
            html = get(archive_url)
            links = exact_lot_links(html, slug, archive_url)
            if not links:
                # Empty page is terminal only after page 1; page 1 empty is a discovery failure.
                if page == 1:
                    raise RuntimeError('past-auctions page returned zero exact lot links')
                completed.add(key)
                state.setdefault('regions_completed', []).append(slug)
                continue
            page_rows = 0
            for item in links:
                try:
                    row = parse_detail(item, label, archive_url)
                except Exception as exc:
                    state.setdefault('failures', []).append({'key': key, 'source_id': item['source_id'], 'url': item['url'], 'error': repr(exc), 'at': now_iso()})
                    failures_this_run += 1
                    continue
                if row:
                    if row['source_id'] not in existing:
                        added += 1
                    existing[row['source_id']] = row
                    page_rows += 1
            # A page can legitimately contain zero commercial lots, but the exact lot discovery must be nonzero.
            completed.add(key)
            state['last_page'] = {'key': key, 'url': archive_url, 'exact_lots_seen': len(links), 'commercial_lots': page_rows}
            state['last_success'] = now_iso()
        except Exception as exc:
            failures_this_run += 1
            state.setdefault('failures', []).append({'key': key, 'url': archive_url, 'error': repr(exc), 'at': now_iso()})
    payload['schema_version'] = 1
    payload['generated_at'] = now_iso()
    payload['lots'] = sorted(existing.values(), key=lambda x: ((x.get('auction_date') or ''), x.get('source') or '', x.get('source_id') or ''), reverse=True)
    save_json(LOTS, payload)
    state['pages_completed'] = sorted(completed)
    state['lots_captured'] = len(payload['lots'])
    state['last_run_added'] = added
    state['last_run_failures'] = failures_this_run
    state['last_run_completed'] = now_iso()
    state['status'] = 'DEGRADED' if failures_this_run else 'RUNNING'
    progress['updated_at'] = now_iso()
    save_json(PROGRESS, progress)
    print(json.dumps({'source': 'Auction House Shared Platform', 'added': added, 'total': len(payload['lots']), 'failures': failures_this_run, 'pages_attempted': len(work)}, indent=2))
    return added


if __name__ == '__main__':
    main()

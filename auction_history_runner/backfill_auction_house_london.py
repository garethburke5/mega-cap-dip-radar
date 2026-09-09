from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

OUT = Path('auction_history_output')
PROGRESS = OUT / 'progress.json'
LOTS = OUT / 'auction_house_london_lots.json'
BASE = 'https://auctionhouselondon.co.uk'
ARCHIVE = BASE + '/past-auctions'
POSTCODE = re.compile(r'\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b', re.I)
LOT_URL = re.compile(r'/lot/[^/?#]+-(\d+)/?$', re.I)
AUCTION_URL = re.compile(r'^/auction/[^/?#]+/?$', re.I)
COMMERCIAL = re.compile(
    r'\b(?:commercial|mixed[- ]use|retail|shop|office|warehouse|industrial|workshop|'
    r'public house|\bpub\b|hotel|restaurant|takeaway|business premises|commercial unit|'
    r'development site|garage(?: block)?|investment property|freehold ground rent|'
    r'ground rent|retail property|commercial development)\b', re.I)

S = requests.Session()
S.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/140 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml',
})


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def clean(v):
    return re.sub(r'\s+', ' ', str(v or '')).strip()


def get(url, timeout=40):
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


def cash(text):
    m = re.search(r'£\s*([\d,]+(?:\.\d+)?)', text or '')
    if not m:
        return None
    try:
        return float(m.group(1).replace(',', ''))
    except ValueError:
        return None


def parse_result(text):
    t = clean(text)
    low = t.lower()
    m = re.search(r'sold\s+(?:after auction\s+)?for\s+£\s*([\d,]+(?:\.\d+)?)', t, re.I)
    if m:
        price = float(m.group(1).replace(',', ''))
        return ('SOLD AFTER' if 'sold after' in low else 'SOLD'), price
    if 'sold prior' in low:
        return 'SOLD PRIOR', None
    if 'sold after' in low:
        return 'SOLD AFTER', None
    if 'withdrawn' in low:
        return 'WITHDRAWN', None
    if 'postponed' in low:
        return 'POSTPONED', None
    if 'unsold' in low:
        return 'UNSOLD', None
    if 'refer to auctioneer' in low:
        return 'REFER TO AUCTIONEER', None
    return 'ARCHIVED', None


def parse_date(text):
    # Auction headings can be ranges such as 19th-20th March 2025. Use first day.
    m = re.search(r'\b(\d{1,2})(?:st|nd|rd|th)?(?:\s*[-–]\s*\d{1,2}(?:st|nd|rd|th)?)?\s+([A-Za-z]+)\s+(20\d{2})\b', text or '', re.I)
    if not m:
        return None
    try:
        return datetime.strptime(f'{m.group(1)} {m.group(2)} {m.group(3)}', '%d %B %Y').date().isoformat()
    except ValueError:
        return None


def discover_auctions(html):
    soup = BeautifulSoup(html, 'html.parser')
    found = {}
    for a in soup.find_all('a', href=True):
        url = urljoin(ARCHIVE, a.get('href')).split('#')[0].split('?')[0]
        path = urlparse(url).path.rstrip('/')
        if not AUCTION_URL.match(path):
            continue
        text = clean(a.get_text(' ', strip=True))
        parent_text = text
        node = a
        for _ in range(4):
            node = getattr(node, 'parent', None)
            if node is None:
                break
            candidate = clean(node.get_text(' ', strip=True))
            if 10 <= len(candidate) <= 700:
                parent_text = candidate
                if parse_date(candidate):
                    break
        date = parse_date(parent_text) or parse_date(text)
        key = path.rsplit('/', 1)[-1]
        found[key] = {'auction_id': key, 'url': url, 'date': date, 'label': parent_text[:250]}
    # Newest first; unknown dates last.
    return sorted(found.values(), key=lambda x: (x.get('date') or '', x['auction_id']), reverse=True)


def lot_cards(html, auction_url):
    soup = BeautifulSoup(html, 'html.parser')
    out = []
    seen = set()
    for a in soup.find_all('a', href=True):
        url = urljoin(auction_url, a.get('href')).split('#')[0].split('?')[0]
        m = LOT_URL.search(urlparse(url).path)
        if not m:
            continue
        sid = m.group(1)
        if sid in seen:
            continue
        seen.add(sid)
        card = clean(a.get_text(' ', strip=True))
        node = a
        for _ in range(7):
            node = getattr(node, 'parent', None)
            if node is None:
                break
            candidate = clean(node.get_text(' ', strip=True))
            if 20 <= len(candidate) <= 2600:
                card = candidate
                if POSTCODE.search(candidate) and re.search(r'\bLOT\s+\d+', candidate, re.I):
                    break
            if len(candidate) > 2600:
                break
        out.append({'source_id': sid, 'url': url, 'card': card})
    return out


def detail_row(item, auction):
    card = clean(item['card'])
    # Commercial/mixed assets are identifiable in catalogue cards. Avoid fetching hundreds of residential details.
    if not COMMERCIAL.search(card):
        return None
    html = get(item['url'])
    soup = BeautifulSoup(html, 'html.parser')
    main = soup.find('main') or soup
    text = clean(main.get_text(' ', strip=True))
    combined = clean(card + ' ' + text)
    if not COMMERCIAL.search(combined):
        return None

    pm = POSTCODE.search(card)
    address = None
    if pm:
        before = card[:pm.end()]
        before = re.sub(r'^.*?\bLOT\s+\d+[A-Z]?\b', '', before, flags=re.I)
        # Drop result/type boilerplate before the address where possible.
        before = re.sub(r'^(?:Sold[^A-Z]*|Unsold[^A-Z]*|Withdrawn|Postponed|Please refer[^A-Z]*)+', '', before, flags=re.I)
        address = clean(before)
    if not address or len(address) < 6:
        # Detail pages publish the address near the top; take the shortest postcode-bearing line/block.
        candidates = []
        for tag in soup.find_all(['h1','h2','h3','p','div']):
            t = clean(tag.get_text(' ', strip=True))
            if POSTCODE.search(t) and 6 <= len(t) <= 320:
                candidates.append(t)
        if candidates:
            address = min(candidates, key=len)
    if not address:
        return None

    lot_number = None
    lm = re.search(r'\bLOT\s+(\d+[A-Z]?)\b', card + ' ' + text[:800], re.I)
    if lm:
        lot_number = f'Lot {lm.group(1)}'
    status, sale_price = parse_result(card + ' ' + text[:900])

    guide = None
    gm = re.search(r'\bGuide(?:\s+Price)?\b[^£]{0,30}£\s*([\d,]+)', combined, re.I)
    if gm:
        guide = float(gm.group(1).replace(',', ''))
    rent = None
    rm = re.search(r'(?:Producing|Rent|Rental Income|Annual Income)[^£]{0,70}£\s*([\d,]+(?:\.\d+)?)\s*(?:Per Annum|p\.?a\.?|pa)', combined, re.I)
    if rm:
        rent = float(rm.group(1).replace(',', ''))
    tenure = 'Freehold' if re.search(r'\bFreehold\b', combined, re.I) else ('Leasehold' if re.search(r'\bLeasehold\b', combined, re.I) else None)

    property_type = 'Commercial'
    if re.search(r'\bMixed\s*Use\b', combined, re.I): property_type = 'Mixed Use'
    elif re.search(r'\b(?:Retail|Shop)\b', combined, re.I): property_type = 'Retail'
    elif re.search(r'\b(?:Warehouse|Industrial|Workshop)\b', combined, re.I): property_type = 'Industrial / Warehouse'
    elif re.search(r'\bOffices?\b', combined, re.I): property_type = 'Office'
    elif re.search(r'\b(?:Pub|Public House|Hotel|Restaurant|Takeaway)\b', combined, re.I): property_type = 'Leisure / Hospitality'
    elif re.search(r'\b(?:Development Site|Commercial Development)\b', combined, re.I): property_type = 'Development'

    image = None
    og = soup.find('meta', attrs={'property': 'og:image'})
    if og and og.get('content'):
        image = urljoin(item['url'], og.get('content'))
    if not image:
        img = main.find('img', src=True)
        if img:
            image = urljoin(item['url'], img.get('src'))

    legal_pack = None
    for a in soup.find_all('a', href=True):
        if 'legal pack' in clean(a.get_text(' ', strip=True)).lower():
            legal_pack = urljoin(item['url'], a.get('href'))
            break

    return {
        'source': 'Auction House London',
        'source_id': item['source_id'],
        'auction_id': auction['auction_id'],
        'url': item['url'],
        'result_page_url': auction['url'],
        'auction_url': auction['url'],
        'evidence_url': item['url'],
        'legal_pack_url': legal_pack,
        'address': address,
        'auction_date': auction.get('date') or parse_date(text),
        'auction_month': (auction.get('date') or '')[:7] or None,
        'lot_number': lot_number,
        'status': status,
        'guide_price': guide,
        'sale_price': sale_price,
        'annual_rent': rent,
        'tenure': tenure,
        'property_type': property_type,
        'description': text[:7000],
        'image_url': image,
        'captured_at': now_iso(),
    }


def main(batch_auctions=4):
    OUT.mkdir(parents=True, exist_ok=True)
    progress = load_json(PROGRESS, {'schema_version': 1, 'updated_at': None, 'sources': {}})
    state = progress.setdefault('sources', {}).setdefault('Auction House London', {
        'status': 'NOT_STARTED', 'auctions_completed': 0, 'lots_captured': 0,
        'completed_auction_ids': [], 'failures': [],
        'ingestion_method': 'server-rendered /past-auctions + exact /lot pages',
    })
    payload = load_json(LOTS, {'schema_version': 1, 'lots': []})
    existing = {str(x.get('source_id')): x for x in payload.get('lots', []) if x.get('source_id')}
    completed = set(state.get('completed_auction_ids') or [])
    state['last_run_started'] = now_iso()
    state['status'] = 'RUNNING'

    try:
        auctions = discover_auctions(get(ARCHIVE))
    except Exception as exc:
        state['status'] = 'DISCOVERY_FAILED'
        state.setdefault('failures', []).append({'stage': 'discover', 'url': ARCHIVE, 'error': repr(exc), 'at': now_iso()})
        progress['updated_at'] = now_iso(); save_json(PROGRESS, progress)
        raise
    if not auctions:
        state['status'] = 'DISCOVERY_FAILED'
        state.setdefault('failures', []).append({'stage': 'discover', 'url': ARCHIVE, 'error': 'zero auction links discovered', 'at': now_iso()})
        progress['updated_at'] = now_iso(); save_json(PROGRESS, progress)
        raise RuntimeError('Auction House London discovery returned zero auctions')

    state['auctions_discovered'] = len(auctions)
    dates = [a['date'] for a in auctions if a.get('date')]
    if dates:
        state['earliest_month_reached'] = min(dates)[:7]
        state['latest_month_seen'] = max(dates)[:7]
    pending = [a for a in auctions if a['auction_id'] not in completed]
    work = pending[:max(1, int(batch_auctions))]
    added = 0
    failures_this_run = 0

    for auction in work:
        try:
            cards = lot_cards(get(auction['url']), auction['url'])
            if not cards:
                raise RuntimeError('auction page returned zero exact lot links')
            commercial_rows = 0
            per_auction_failures = 0
            for item in cards:
                try:
                    row = detail_row(item, auction)
                    if not row:
                        continue
                    if row['source_id'] not in existing:
                        added += 1
                    existing[row['source_id']] = row
                    commercial_rows += 1
                except Exception as exc:
                    per_auction_failures += 1
                    failures_this_run += 1
                    state.setdefault('failures', []).append({'auction_id': auction['auction_id'], 'source_id': item['source_id'], 'url': item['url'], 'error': repr(exc), 'at': now_iso()})
            # Never mark an auction complete if an exact commercial detail failed.
            if per_auction_failures == 0:
                completed.add(auction['auction_id'])
                state['last_success'] = now_iso()
                state['last_auction'] = {'auction_id': auction['auction_id'], 'url': auction['url'], 'date': auction.get('date'), 'exact_lots_seen': len(cards), 'commercial_lots': commercial_rows}
        except Exception as exc:
            failures_this_run += 1
            state.setdefault('failures', []).append({'auction_id': auction['auction_id'], 'url': auction['url'], 'error': repr(exc), 'at': now_iso()})

    payload['schema_version'] = 1
    payload['generated_at'] = now_iso()
    payload['lots'] = sorted(existing.values(), key=lambda x: ((x.get('auction_date') or ''), x.get('source_id') or ''), reverse=True)
    save_json(LOTS, payload)

    state['completed_auction_ids'] = sorted(completed)
    state['auctions_completed'] = len(completed)
    state['lots_captured'] = len(payload['lots'])
    state['remaining_auctions'] = max(0, len(auctions) - len(completed))
    state['last_run_added'] = added
    state['last_run_failures'] = failures_this_run
    state['last_run_completed'] = now_iso()
    if state['remaining_auctions'] == 0 and failures_this_run == 0:
        state['status'] = 'CAUGHT_UP'
    elif failures_this_run:
        state['status'] = 'DEGRADED'
    else:
        state['status'] = 'RUNNING'
    progress['updated_at'] = now_iso()
    save_json(PROGRESS, progress)
    print(json.dumps({'source': 'Auction House London', 'discovered': len(auctions), 'completed': len(completed), 'added': added, 'total': len(payload['lots']), 'remaining': state['remaining_auctions'], 'failures': failures_this_run}, indent=2))
    return added


if __name__ == '__main__':
    main()

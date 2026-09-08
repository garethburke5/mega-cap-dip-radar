from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

OUT = Path('auction_history_output')
V2 = OUT / 'history_v2'
POSTCODE_RE = re.compile(r'\b([A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2})\b', re.I)
SOURCE_FILES = [
    ('Allsop Commercial', OUT / 'allsop_lots.json'),
    ('Savills', OUT / 'savills_lots.json'),
]


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def text(v):
    return re.sub(r'\s+', ' ', str(v or '')).strip()


def postcode(address):
    m = POSTCODE_RE.search(text(address).upper())
    return re.sub(r'\s+', '', m.group(1).upper()) if m else None


def norm_address(address):
    s = text(address).lower().replace('&', ' and ')
    s = POSTCODE_RE.sub(' ', s)
    for a, b in {'street':'st','road':'rd','avenue':'ave','lane':'ln','drive':'dr'}.items():
        s = re.sub(rf'\b{a}\b', f' {b} ', s)
    return text(re.sub(r'[^a-z0-9]+', ' ', s))


def building_tokens(address):
    return re.findall(r'\b\d+[a-z]?\b', norm_address(address))[:6]


def property_id(address):
    pc = postcode(address) or 'NOPOSTCODE'
    return hashlib.sha1(f'{pc}|{norm_address(address)}'.encode('utf-8')).hexdigest()[:20]


def event_id(item):
    seed = '|'.join(text(item.get(k)).lower() for k in ('source','source_id','auction_id','lot_number','url'))
    return hashlib.sha1(seed.encode('utf-8')).hexdigest()[:24]


def normalized_date(item):
    explicit = text(item.get('auction_date'))
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', explicit):
        return explicit
    ms = item.get('auction_date_ms')
    if isinstance(ms, (int, float)):
        try:
            return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).date().isoformat()
        except Exception:
            pass
    month = text(item.get('auction_month'))
    return f'{month}-01' if re.fullmatch(r'\d{4}-\d{2}', month) else None


def load_sources():
    rows = []
    counts = {}
    for name, path in SOURCE_FILES:
        if not path.exists():
            counts[name] = 0
            continue
        try:
            payload = json.loads(path.read_text(encoding='utf-8'))
            lots = payload.get('lots') or []
        except Exception:
            lots = []
        counts[name] = len(lots)
        rows.extend(lots)
    return rows, counts


def normalize_item(item):
    address = text(item.get('address'))
    source = text(item.get('source'))
    listing = text(item.get('url'))
    source_id = text(item.get('source_id'))
    if not (address and source and listing and source_id):
        return None, {'source': source or None, 'source_id': source_id or None, 'reason': 'missing address/source/evidence/source_id'}
    pc = postcode(address)
    pid = property_id(address)
    eid = event_id(item)
    auction_url = text(item.get('auction_url')) or text(item.get('result_page_url')) or None
    results_url = text(item.get('result_page_url')) or auction_url
    ev = {
        'event_id': eid,
        'property_id': pid,
        'source': source,
        'source_id': source_id,
        'auction_id': text(item.get('auction_id')) or None,
        'auction_date': normalized_date(item),
        'auction_month': text(item.get('auction_month')) or None,
        'lot_number': text(item.get('lot_number')) or None,
        'address_as_published': address,
        'postcode_normalized': pc,
        'building_tokens': building_tokens(address),
        'address_normalized': norm_address(address),
        'status': item.get('status'),
        'guide_price': item.get('guide_price'),
        'guide_price_lower': item.get('guide_price_lower'),
        'guide_price_upper': item.get('guide_price_upper'),
        'guide_price_text': item.get('guide_price_text'),
        'sale_price': item.get('sale_price'),
        'available_price': item.get('available_price'),
        'annual_rent': item.get('annual_rent'),
        'gross_yield': item.get('gross_yield'),
        'net_yield': item.get('net_yield'),
        'tenure': item.get('tenure'),
        'tenant': item.get('tenant'),
        'lease_term': item.get('lease_term'),
        'lease_start': item.get('lease_start'),
        'lease_expiry': item.get('lease_expiry'),
        'break_date': item.get('break_date'),
        'occupation': item.get('occupation'),
        'property_type': item.get('property_type'),
        'property_types': item.get('property_types'),
        'area_sqft': item.get('area_sqft'),
        'description': item.get('description'),
        'image_url': item.get('image_url'),
        'features': item.get('features') or [],
        'live_addendum': item.get('live_addendum'),
        'evidence': {
            'listing_url': listing,
            'results_url': results_url,
            'auction_url': auction_url,
            'legal_pack_url': item.get('legal_pack_url'),
            'source_id': source_id,
            'captured_at': item.get('captured_at'),
        },
        'captured_at': item.get('captured_at'),
    }
    return ev, None


def build_payload(rows):
    events, rejected, by_postcode = [], [], {}
    seen = set()
    for item in rows:
        ev, rejection = normalize_item(item)
        if rejection:
            rejected.append(rejection)
            continue
        if ev['event_id'] in seen:
            continue
        seen.add(ev['event_id'])
        events.append(ev)
        pc = ev.get('postcode_normalized')
        if pc:
            by_postcode.setdefault(pc, []).append({
                'event_id': ev['event_id'],
                'property_id': ev['property_id'],
                'address': ev['address_as_published'],
                'address_normalized': ev['address_normalized'],
                'building_tokens': ev['building_tokens'],
                'auction_date': ev['auction_date'],
                'source': ev['source'],
            })
    events.sort(key=lambda e: ((e.get('auction_date') or ''), e.get('source') or '', e.get('source_id') or ''), reverse=True)
    for rows_for_pc in by_postcode.values():
        rows_for_pc.sort(key=lambda r: ((r.get('auction_date') or ''), r.get('source') or '', r.get('event_id') or ''), reverse=True)
    return events, rejected, by_postcode


def write_pair(events, rejected, by_postcode, events_path, index_path, source_label):
    generated = now_iso()
    events_path.write_text(json.dumps({
        'schema_version': 2,
        'generated_at': generated,
        'source': source_label,
        'accepted_event_count': len(events),
        'rejected_count': len(rejected),
        'rejected': rejected,
        'events': events,
    }, indent=2, ensure_ascii=False), encoding='utf-8')
    index_path.write_text(json.dumps({
        'schema_version': 2,
        'generated_at': generated,
        'source': source_label,
        'postcode_count': len(by_postcode),
        'event_count': len(events),
        'by_postcode': by_postcode,
    }, separators=(',', ':'), ensure_ascii=False), encoding='utf-8')


def export():
    raw_rows, source_counts = load_sources()
    events, rejected, by_postcode = build_payload(raw_rows)
    V2.mkdir(parents=True, exist_ok=True)

    # New production multi-source files.
    write_pair(events, rejected, by_postcode, V2 / 'history_events.json', V2 / 'history_index.json', 'Auction Sniper multi-source')

    # Backward-compatible Allsop files while the private app migrates.
    all_all = [r for r in raw_rows if text(r.get('source')) == 'Allsop Commercial']
    a_events, a_rejected, a_index = build_payload(all_all)
    write_pair(a_events, a_rejected, a_index, V2 / 'allsop_events.json', V2 / 'allsop_index.json', 'Allsop Commercial')

    sale_count = sum(1 for e in events if e.get('sale_price') is not None)
    evidence_count = sum(1 for e in events if (e.get('evidence') or {}).get('listing_url'))
    source_event_counts = {}
    for e in events:
        source_event_counts[e['source']] = source_event_counts.get(e['source'], 0) + 1
    summary = {
        'schema_version': 2,
        'generated_at': now_iso(),
        'sources': source_counts,
        'events_by_source': source_event_counts,
        'source_rows': len(raw_rows),
        'accepted_events': len(events),
        'unique_event_ids': len({e['event_id'] for e in events}),
        'rejected': len(rejected),
        'postcodes_indexed': len(by_postcode),
        'events_with_sale_price': sale_count,
        'events_with_listing_evidence': evidence_count,
        'source_rows_accounted_for': len(events) + len(rejected),
        'idempotency_ok': len({e['event_id'] for e in events}) == len(events),
        'evidence_coverage_pct': round((evidence_count / len(events) * 100.0), 2) if events else 0.0,
    }
    (V2 / 'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    export()

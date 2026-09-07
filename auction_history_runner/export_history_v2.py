from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

OUT = Path('auction_history_output')
SOURCE = OUT / 'allsop_lots.json'
V2 = OUT / 'history_v2'
EVENTS = V2 / 'allsop_events.json'
INDEX = V2 / 'allsop_index.json'
SUMMARY = V2 / 'summary.json'
POSTCODE_RE = re.compile(r'\b([A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2})\b', re.I)


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
    replacements = {'street':'st','road':'rd','avenue':'ave','lane':'ln','drive':'dr'}
    for a,b in replacements.items():
        s = re.sub(rf'\b{a}\b', f' {b} ', s)
    s = re.sub(r'[^a-z0-9]+', ' ', s)
    return text(s)


def building_tokens(address):
    return re.findall(r'\b\d+[a-z]?\b', norm_address(address))[:6]


def property_id(address):
    pc = postcode(address) or 'NOPOSTCODE'
    seed = f'{pc}|{norm_address(address)}'
    return hashlib.sha1(seed.encode('utf-8')).hexdigest()[:20]


def event_id(item):
    seed = '|'.join(text(item.get(k)).lower() for k in ('source','source_id','auction_id','lot_number','url'))
    return hashlib.sha1(seed.encode('utf-8')).hexdigest()[:24]


def auction_date(item):
    ms = item.get('auction_date_ms')
    if isinstance(ms, (int, float)):
        try:
            return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).date().isoformat()
        except Exception:
            pass
    month = text(item.get('auction_month'))
    return f'{month}-01' if re.fullmatch(r'\d{4}-\d{2}', month) else None


def export():
    raw = json.loads(SOURCE.read_text(encoding='utf-8'))
    lots = raw.get('lots') or []
    events = []
    by_postcode = {}
    rejected = []

    for item in lots:
        address = text(item.get('address'))
        source = text(item.get('source'))
        listing = text(item.get('url'))
        source_id = text(item.get('source_id'))
        if not (address and source and listing and source_id):
            rejected.append({'source_id': source_id or None, 'reason': 'missing address/source/evidence/source_id'})
            continue
        pc = postcode(address)
        pid = property_id(address)
        eid = event_id(item)
        ev = {
            'event_id': eid,
            'property_id': pid,
            'source': source,
            'source_id': source_id,
            'auction_id': text(item.get('auction_id')) or None,
            'auction_date': auction_date(item),
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
            'annual_rent': item.get('annual_rent'),
            'gross_yield': item.get('gross_yield'),
            'net_yield': item.get('net_yield'),
            'tenure': item.get('tenure'),
            'tenant': item.get('tenant'),
            'lease_term': item.get('lease_term'),
            'property_type': item.get('property_type'),
            'property_types': item.get('property_types'),
            'image_url': item.get('image_url'),
            'features': item.get('features') or [],
            'live_addendum': item.get('live_addendum'),
            'evidence': {
                'listing_url': listing,
                'results_url': text(item.get('result_page_url')) or None,
                'auction_url': text(item.get('result_page_url')) or None,
                'legal_pack_url': None,
                'source_id': source_id,
                'captured_at': item.get('captured_at'),
            },
            'captured_at': item.get('captured_at'),
        }
        events.append(ev)
        if pc:
            by_postcode.setdefault(pc, []).append({
                'event_id': eid,
                'property_id': pid,
                'address': address,
                'address_normalized': ev['address_normalized'],
                'building_tokens': ev['building_tokens'],
                'auction_date': ev['auction_date'],
                'source': source,
            })

    events.sort(key=lambda e: ((e.get('auction_date') or ''), e.get('source_id') or ''), reverse=True)
    for rows in by_postcode.values():
        rows.sort(key=lambda r: (r.get('auction_date') or '', r.get('event_id') or ''), reverse=True)

    generated = now_iso()
    sale_count = sum(1 for e in events if e.get('sale_price') is not None)
    evidence_count = sum(1 for e in events if (e.get('evidence') or {}).get('listing_url'))
    unique_event_ids = len({e['event_id'] for e in events})
    V2.mkdir(parents=True, exist_ok=True)
    EVENTS.write_text(json.dumps({
        'schema_version': 2,
        'generated_at': generated,
        'source': 'Allsop Commercial',
        'source_row_count': len(lots),
        'accepted_event_count': len(events),
        'rejected_count': len(rejected),
        'rejected': rejected,
        'events': events,
    }, indent=2, ensure_ascii=False), encoding='utf-8')
    INDEX.write_text(json.dumps({
        'schema_version': 2,
        'generated_at': generated,
        'source': 'Allsop Commercial',
        'postcode_count': len(by_postcode),
        'event_count': len(events),
        'by_postcode': by_postcode,
    }, separators=(',', ':'), ensure_ascii=False), encoding='utf-8')
    summary = {
        'schema_version': 2,
        'generated_at': generated,
        'source': 'Allsop Commercial',
        'source_rows': len(lots),
        'accepted_events': len(events),
        'unique_event_ids': unique_event_ids,
        'rejected': len(rejected),
        'postcodes_indexed': len(by_postcode),
        'events_with_sale_price': sale_count,
        'events_with_listing_evidence': evidence_count,
        'source_rows_accounted_for': len(events) + len(rejected),
        'idempotency_ok': unique_event_ids == len(events),
        'evidence_coverage_pct': round((evidence_count / len(events) * 100.0), 2) if events else 0.0,
    }
    SUMMARY.write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    export()

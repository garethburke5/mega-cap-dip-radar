from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import requests

OUT = Path('auction_history_output')
DISCOVERY = OUT / 'allsop_discovery.json'
PROGRESS = OUT / 'progress.json'
LOTS = OUT / 'allsop_lots.json'
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131 Safari/537.36',
    'Accept': 'application/json,text/plain,*/*',
    'Referer': 'https://www.allsop.co.uk/property-search',
}


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def load(path, default):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return default


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding='utf-8')


def num(v):
    try:
        return float(v) if v not in (None, '') else None
    except Exception:
        return None


def tenant_summary(raw):
    if not raw:
        return None, None
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
        rows = data.get('rows') or [] if isinstance(data, dict) else []
        lessees = []
        leases = []
        for row in rows:
            lessee = str(row.get('lessee') or '').strip()
            lease = str(row.get('lease') or '').strip()
            if lessee and lessee not in lessees:
                lessees.append(lessee)
            if lease and lease not in leases:
                leases.append(lease)
        return '; '.join(lessees) or None, ' | '.join(leases) or None
    except Exception:
        return None, None


def api_page(auction_id, page):
    params = {
        'auction_id': auction_id,
        'view': 'table',
        'page': page,
        'react': '',
    }
    r = requests.get('https://www.allsop.co.uk/api/search', params=params, headers=HEADERS, timeout=35)
    r.raise_for_status()
    payload = r.json()
    data = payload.get('data') or {}
    return data, payload


def infer_total(data):
    for key in ('total', 'total_results', 'totalResults', 'count', 'total_count', 'totalCount'):
        value = data.get(key)
        if isinstance(value, (int, float)):
            return int(value)
    return None


def fetch_all_auction_results(auction):
    aid = auction['auction_id']
    seen = {}
    page_shapes = []
    total_hint = None
    previous_signature = None
    exhausted = False

    for page in range(1, 31):
        data, payload = api_page(aid, page)
        rows = data.get('results') or []
        if total_hint is None:
            total_hint = infer_total(data)
        ids = [str(r.get('allsop_lotid') or r.get('reference') or '') for r in rows]
        signature = tuple(ids)
        page_shapes.append({
            'page': page,
            'rows': len(rows),
            'data_keys': list(data.keys()),
            'first_id': ids[0] if ids else None,
            'last_id': ids[-1] if ids else None,
            'total_hint': total_hint,
        })
        if not rows:
            exhausted = True
            break
        if previous_signature is not None and signature == previous_signature:
            break
        new_count = 0
        for row in rows:
            key = str(row.get('allsop_lotid') or row.get('reference') or '')
            if key and key not in seen:
                seen[key] = row
                new_count += 1
        if new_count == 0:
            break
        if total_hint is not None and len(seen) >= total_hint:
            exhausted = True
            break
        if len(rows) < 20:
            exhausted = True
            break
        previous_signature = signature

    if total_hint is not None:
        complete = len(seen) >= total_hint
    else:
        complete = exhausted
    return list(seen.values()), complete, total_hint, page_shapes


def transform(row, auction):
    tenant, lease = tenant_summary(row.get('tenancy_table') or row.get('tenant'))
    lot_no = row.get('lot_number') or row.get('allsop_lotnumber')
    address = row.get('full_address') or row.get('allsop_address')
    aid = auction['auction_id']
    evidence_url = f"{auction['results_url']}#lot-{lot_no}" if lot_no else auction['results_url']
    image_id = row.get('featured_image_file_id') or row.get('featured_image_path') or row.get('image_file_id')
    image_url = f'https://www.allsop.co.uk/api/image/{image_id}/1200/900' if image_id else None
    guide_lower = num(row.get('guide_price_lower'))
    guide_upper = num(row.get('guide_price_upper'))
    guide = guide_lower if guide_lower is not None else None
    return {
        'source': 'Allsop Commercial',
        'source_id': str(row.get('allsop_lotid') or row.get('reference') or ''),
        'auction_id': aid,
        'url': evidence_url,
        'result_page_url': auction['results_url'],
        'address': address,
        'lot_number': str(lot_no) if lot_no is not None else None,
        'auction_date_ms': row.get('auction_date'),
        'auction_month': auction.get('month'),
        'status': row.get('lot_status') or row.get('lotStatus') or row.get('allsop_lotstatus'),
        'guide_price': guide,
        'guide_price_lower': guide_lower,
        'guide_price_upper': guide_upper,
        'guide_price_text': row.get('guide_price_text') or row.get('price'),
        'sale_price': num(row.get('sale_price')),
        'annual_rent': num(row.get('income') or row.get('current_rent_per_annum')),
        'gross_yield': num(row.get('yield')),
        'net_yield': num(row.get('net_yield')),
        'tenure': row.get('property_tenure') or row.get('allsop_propertytenure'),
        'tenant': tenant,
        'lease_term': lease,
        'property_type': row.get('property_byline') or row.get('allsop_propertybyline'),
        'property_types': row.get('property_types') or row.get('comm_property_types'),
        'image_url': image_url,
        'features': row.get('features') or [],
        'live_addendum': row.get('live_addendum'),
        'captured_at': now_iso(),
    }


def main(batch_size=2):
    discovery = load(DISCOVERY, {})
    auctions = discovery.get('auctions') or []
    progress = load(PROGRESS, {'schema_version': 1, 'sources': {}})
    state = progress.setdefault('sources', {}).setdefault('Allsop Commercial', {})
    completed = set(state.get('completed_auction_ids') or [])
    lot_db = load(LOTS, {'schema_version': 2, 'generated_at': None, 'lots': []})
    existing = {x.get('source_id'): x for x in lot_db.get('lots', []) if x.get('source_id')}
    failures = state.setdefault('failures', [])

    selected = [a for a in auctions if a.get('auction_id') not in completed][:batch_size]
    state.update({
        'status': 'RUNNING' if selected else 'CAUGHT UP',
        'auctions_discovered': len(auctions),
        'auctions_completed': len(completed),
        'lots_captured': len(existing),
        'last_run_started': now_iso(),
        'ingestion_method': 'Allsop /api/search JSON',
    })

    for auction in selected:
        aid = auction['auction_id']
        try:
            rows, complete, total_hint, page_shapes = fetch_all_auction_results(auction)
            if not rows:
                raise RuntimeError('Allsop API returned zero historical lots')
            if not complete:
                raise RuntimeError(f'Pagination not proven complete: captured={len(rows)} total_hint={total_hint} pages={page_shapes}')
            valid = 0
            for row in rows:
                item = transform(row, auction)
                if item.get('source_id') and item.get('address'):
                    existing[item['source_id']] = item
                    valid += 1
            if valid == 0:
                raise RuntimeError(f'API returned {len(rows)} rows but none had stable ID + address')
            completed.add(aid)
            state['completed_auction_ids'] = sorted(completed)
            state['auctions_completed'] = len(completed)
            state['lots_captured'] = len(existing)
            state['last_success'] = now_iso()
            state['last_auction'] = {
                'auction_id': aid,
                'label': auction.get('label'),
                'rows_captured': valid,
                'total_hint': total_hint,
                'page_shapes': page_shapes,
            }
        except Exception as exc:
            failures.append({'auction_id': aid, 'label': auction.get('label'), 'error': f'{type(exc).__name__}: {exc}', 'at': now_iso()})

    remaining = [a for a in auctions if a.get('auction_id') not in completed]
    completed_months = [a.get('month') for a in auctions if a.get('auction_id') in completed and a.get('month')]
    state['earliest_month_reached'] = min(completed_months) if completed_months else None
    state['remaining_auctions'] = len(remaining)
    state['status'] = 'CAUGHT UP' if not remaining else ('RUNNING' if completed else 'DEGRADED')
    state['last_run_completed'] = now_iso()
    progress['updated_at'] = now_iso()
    lot_db['schema_version'] = 2
    lot_db['generated_at'] = now_iso()
    lot_db['lots'] = sorted(existing.values(), key=lambda x: (x.get('auction_month') or '', int(x.get('lot_number') or 0)), reverse=True)
    save(LOTS, lot_db)
    save(PROGRESS, progress)
    print(json.dumps({
        'status': state['status'],
        'auctions_discovered': len(auctions),
        'auctions_completed': len(completed),
        'remaining_auctions': len(remaining),
        'lots_captured': len(existing),
        'failures': len(failures),
        'last_auction': state.get('last_auction'),
    }, indent=2))


if __name__ == '__main__':
    main()

from __future__ import annotations

import json
import re
from urllib.parse import urlparse

from auction_history_runner import backfill_savills as s

# Older Savills catalogues can ignore the modern property_type route even though
# their server-rendered unfiltered auction pages remain intact. This fallback is
# deliberately conservative: it is used only for events that the primary
# commercial-filter collector has already failed, and only retains rows whose
# catalogue text contains clear commercial/mixed-use evidence.
COMMERCIAL_MARKERS = re.compile(
    r"\b(?:shop|retail|commercial|office|industrial|warehouse|factory|workshop|"
    r"public house|pub|restaurant|takeaway|cafe|supermarket|store|business premises|"
    r"mixed[- ]use|commercial unit|ground floor unit|upper parts?|head lease|"
    r"ground rent|investment let|let at £|leased to|tenant|fri lease|care home|"
    r"garage site|lock[- ]?up garages?|development site|freehold site)\b",
    re.I,
)
RESIDENTIAL_ONLY = re.compile(
    r"\b(?:flat|maisonette|house|bungalow|apartment|bedroom)\b", re.I
)


def unfiltered_url(event_url: str, page: int) -> str:
    return event_url.rstrip('/') if page == 1 else event_url.rstrip('/') + f'/page-{page}'


def clearly_commercial(row: dict) -> bool:
    text = ' '.join([
        s.clean(row.get('address')),
        ' '.join(s.clean(x) for x in (row.get('features') or [])),
    ])
    if not COMMERCIAL_MARKERS.search(text):
        return False
    # A residential word does not exclude a mixed-use lot if there is explicit
    # commercial evidence; the marker is retained only to make this policy clear.
    return True


def crawl_legacy_event(event: dict):
    first_url = unfiltered_url(event['url'], 1)
    first_html = s.get(first_url)
    pages = s.max_pages(first_html)
    collected = []
    page_shapes = []
    for page in range(1, pages + 1):
        url = unfiltered_url(event['url'], page)
        html = first_html if page == 1 else s.get(url)
        rows = s.parse_page(event, url, html)
        commercial = [row for row in rows if clearly_commercial(row)]
        collected.extend(commercial)
        page_shapes.append({
            'page': page,
            'rows_seen': len(rows),
            'commercial_rows': len(commercial),
            'url': url,
        })
    dedup = {str(row['source_id']): row for row in collected}
    return list(dedup.values()), {
        'pages': pages,
        'page_shapes': page_shapes,
        'unique_rows': len(dedup),
        'legacy_fallback': 'unfiltered server-rendered pages + strict commercial markers',
    }


def main(max_events: int = 20):
    progress = s.load_json(s.PROGRESS_FILE, {'schema_version': 1, 'sources': {}})
    source = (progress.get('sources') or {}).get('Savills') or {}
    failures = [x for x in source.get('failures', []) if x.get('auction_id')]
    if not failures:
        print(json.dumps({'legacy_candidates': 0, 'repaired': 0}, indent=2))
        return

    events = {str(e['auction_id']): e for e in s.discover_events()}
    lot_payload = s.load_json(s.LOTS_FILE, {'schema_version': 1, 'source': 'Savills', 'lots': []})
    existing = {str(x.get('source_id')): x for x in lot_payload.get('lots', []) if x.get('source_id')}
    completed = set(str(x) for x in source.get('completed_auction_ids', []))
    repaired = 0
    repaired_ids = set()
    last_auction = source.get('last_auction')

    for failure in failures[:max_events]:
        aid = str(failure.get('auction_id'))
        event = events.get(aid)
        if not event or aid in completed:
            continue
        try:
            rows, evidence = crawl_legacy_event(event)
            if not rows:
                continue
            for row in rows:
                existing[str(row['source_id'])] = row
            completed.add(aid)
            repaired_ids.add(aid)
            repaired += 1
            last_auction = {**event, **evidence}
        except Exception:
            # Keep the original primary-collector failure visible. The fallback
            # must never turn an uncertain scrape into a false completion.
            continue

    if not repaired:
        print(json.dumps({'legacy_candidates': len(failures), 'repaired': 0}, indent=2))
        return

    lots = list(existing.values())
    lots.sort(key=lambda x: ((x.get('auction_date') or ''), str(x.get('lot_number') or ''), str(x.get('source_id') or '')), reverse=True)
    s.save_json(s.LOTS_FILE, {
        'schema_version': 1,
        'source': 'Savills',
        'generated_at': s.now_iso(),
        'lots': lots,
    }, compact=True)

    all_events = list(events.values())
    remaining = max(0, len(all_events) - len(completed))
    source['completed_auction_ids'] = sorted(completed)
    source['auctions_completed'] = len(completed)
    source['lots_captured'] = len(lots)
    source['remaining_auctions'] = remaining
    source['earliest_month_reached'] = min((x.get('auction_month') for x in lots if x.get('auction_month')), default=None)
    source['failures'] = [x for x in source.get('failures', []) if str(x.get('auction_id')) not in repaired_ids]
    source['last_auction'] = last_auction
    source['last_success'] = s.now_iso()
    source['last_run_completed'] = s.now_iso()
    source['legacy_fallback_policy'] = 'Only failed events; unfiltered exact auction pages; strict commercial evidence required'
    source['status'] = 'CAUGHT_UP' if remaining == 0 and not source['failures'] else 'BACKFILLING'
    s.merge_global_progress(source)

    print(json.dumps({
        'legacy_candidates': len(failures),
        'repaired': repaired,
        'auctions_completed': len(completed),
        'lots_captured': len(lots),
        'remaining_auctions': remaining,
    }, indent=2))


if __name__ == '__main__':
    main()

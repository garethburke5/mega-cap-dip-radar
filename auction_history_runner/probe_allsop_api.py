from __future__ import annotations

import json
from pathlib import Path
import requests

OUT=Path('auction_history_output')
discovery=json.loads((OUT/'allsop_discovery.json').read_text(encoding='utf-8'))
results=[]
headers={'User-Agent':'Mozilla/5.0','Accept':'application/json,text/plain,*/*','Referer':'https://www.allsop.co.uk/property-search'}
for auction in (discovery.get('auctions') or [])[:2]:
    aid=auction['auction_id']
    url=f'https://www.allsop.co.uk/api/search?auction_id={aid}&view=table&react'
    r=requests.get(url,headers=headers,timeout=30)
    rec={'auction_id':aid,'label':auction.get('label'),'url':url,'status':r.status_code,'content_type':r.headers.get('content-type'),'text_prefix':r.text[:2000]}
    try:
        data=r.json()
        rec['json_type']=type(data).__name__
        if isinstance(data,dict):
            rec['top_keys']=list(data.keys())
            rec['json_sample']=data
        elif isinstance(data,list):
            rec['list_len']=len(data)
            rec['json_sample']=data[:3]
    except Exception as exc:
        rec['json_error']=f'{type(exc).__name__}: {exc}'
    results.append(rec)
(OUT/'allsop_api_probe.json').write_text(json.dumps({'results':results},indent=2,ensure_ascii=False),encoding='utf-8')
print(json.dumps([{'status':x['status'],'type':x.get('json_type'),'keys':x.get('top_keys')} for x in results],indent=2))

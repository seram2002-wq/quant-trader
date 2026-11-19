"""DART 응답 확인 (인증키는 출력하지 않음)

    python tools/dart_check.py
"""
import os
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / '.env', override=True)
k = os.getenv('DART_API_KEY', '').strip()
corps = pd.read_csv(ROOT / 'data/research/dart/corps.csv', dtype=str).fillna('')
listed = corps[corps.stock_code != ''].corp_code.tolist()
for label, codes, year, rep in (('삼성전자 1개, 2023 사업보고서', ['00126380'], '2023', '11011'),
                                ('100개, 2023 사업보고서', listed[:100], '2023', '11011'),
                                ('20개, 2015 1분기', listed[:20], '2015', '11013'),
                                ('100개, 2015 1분기', listed[:100], '2015', '11013')):
    res = requests.get('https://opendart.fss.or.kr/api/fnlttMultiAcnt.json', timeout=30, params={
        'crtfc_key': k, 'corp_code': ','.join(codes), 'bsns_year': year, 'reprt_code': rep})
    print(f'\n[{label}] HTTP {res.status_code}, {res.headers.get("content-type")}, 주소 길이 {len(res.url)}')
    print(res.text[:300].replace(k, '***') if k else res.text[:300])

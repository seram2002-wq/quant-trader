"""DART 공시 목록 저장 (장 마감 반전 악재 필터 · LLM 백테스트용 자료 쌓기)

    python tools/collect_dart.py              오늘 공시 저장
    python tools/collect_dart.py 20261119     특정 날짜 공시 저장

run.py가 자동으로 부른다 (run.py가 도는 동안 따로 실행하지 말 것: 같은 파일을 둘이 고쳐 쓰게 됨)
    시작할 때    : 직전 거래일부터 오늘까지 (월요일·연휴 다음 날에도 직전 거래일 저녁 공시까지 채움)
    장중         : 오늘 새 공시만, 10분마다 (14:30 ~ 15:00 장 마감 반전 v2 매수 시간에는 1분마다)
    장 마감 뒤   : 오늘 전체 다시 확인
data/dart/YYYYMMDD.csv 로 저장 (git 제외).

rcept_dt에는 날짜만 있고 시각이 없다. 그래서 처음 본 시각(collected_at)을 기록해 두고,
이후 같은 공시를 다시 받아도 collected_at은 바꾸지 않는다. 백테스트에서는 "collected_at
이후에만 알 수 있었다"로 처리하면 미래 정보가 섞이지 않는다.
"""
import csv
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / '.env', override=True)

API_URL = 'https://opendart.fss.or.kr/api/list.json'
OUT_DIR = ROOT / 'data' / 'dart'
FIELDS = [
    'rcept_no',      # 접수번호 (고유키, 앞 8자리 YYYYMMDD)
    'rcept_dt',      # 접수일자 (YYYYMMDD, 시각 없음)
    'corp_cls',      # 법인구분 (Y 유가, K 코스닥, N 코넥스, E 기타)
    'corp_code',     # 고유번호 (8자리)
    'corp_name',     # 회사명
    'stock_code',    # 종목코드 (비상장은 빈칸)
    'report_nm',     # 공시 제목 (기재정정 등 포함)
    'flr_nm',        # 제출인
    'rm',            # 비고 (유 유가증권, 코 코스닥, 정 정정 등)
    'collected_at',  # 처음 받은 시각 (YYYY-MM-DD HH:MM:SS)
]


def path_of(day):
    return OUT_DIR / f'{day}.csv'


def load(day):
    """저장된 공시 {rcept_no: row}"""
    p = path_of(day)
    if not p.exists():
        return {}
    with open(p, encoding='utf-8-sig', newline='') as f:
        return {r['rcept_no']: r for r in csv.DictReader(f) if r.get('rcept_no')}


def fetch(api_key, day, known=(), log=print):
    """그날 공시를 최신순으로 받는다. known에 있는 접수번호가 나오는 페이지에서 멈춘다 (새 것만)"""
    rows, page = [], 1
    while True:
        try:
            res = requests.get(API_URL, timeout=10, params={
                'crtfc_key': api_key, 'bgn_de': day, 'end_de': day, 'sort': 'date', 'sort_mth': 'desc',
                'page_no': page, 'page_count': 100})
            data = res.json()
        except (requests.RequestException, ValueError) as ex:
            log(f'DART 공시 조회 오류 (page {page}) : {ex}')
            break
        status = data.get('status')
        if status == '013':                          # 자료 없음
            break
        if status != '000':
            log(f'DART 응답 {status} : {data.get("message", "")}')
            break
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        items = data.get('list') or []
        seen_known = False
        for item in items:
            row = {k: (item.get(k) or '').strip() for k in FIELDS if k != 'collected_at'}
            row['collected_at'] = now
            if row['rcept_no'] in known:
                seen_known = True
            else:
                rows.append(row)
        if seen_known or page >= int(data.get('total_page') or 1):
            break
        page += 1
        time.sleep(0.15)
    return rows


def collect_dart(day=None, log=print, quiet=False, full=True):
    """공시를 받아 data/dart/YYYYMMDD.csv에 더한다. 새로 더한 건수를 돌려준다

    full=False면 이미 받은 공시가 나오는 페이지에서 멈춘다 (장중에 빠르게 새 것만).
    full=True면 그날 전체를 다시 훑어 빠진 것을 채운다 (시작할 때, 장 마감 뒤).
    """
    api_key = os.getenv('DART_API_KEY', '').strip()
    if not api_key:
        if not quiet:
            log('DART_API_KEY가 없어 공시 저장을 건너뜁니다.')
        return 0
    day = day or datetime.now().strftime('%Y%m%d')
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    existing = load(day)
    known = set(existing)
    new = fetch(api_key, day, () if full else known, log)
    new = [r for r in new if r['rcept_no'] not in known]
    for r in new:
        existing.setdefault(r['rcept_no'], r)            # 처음 본 시각을 지킨다
    if new or not path_of(day).exists():
        merged = sorted(existing.values(), key=lambda x: x['rcept_no'])
        tmp = path_of(day).with_suffix('.tmp')
        with open(tmp, 'w', newline='', encoding='utf-8-sig') as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            w.writeheader()
            w.writerows(merged)
        os.replace(tmp, path_of(day))
    if new and not quiet:
        listed = sum(1 for r in existing.values() if r.get('stock_code'))
        log(f'DART 공시 {day} : 새로 {len(new)}건, 모두 {len(existing)}건 (상장사 {listed}건)')
    return len(new)


def collect_recent(log=print):
    """직전 거래일부터 오늘까지 다시 훑는다. 월요일·연휴 다음 날에도 직전 거래일 저녁 공시까지 채운다"""
    from trader.disclosures import previous_trading_day
    today = datetime.now().date()
    d, total = previous_trading_day(today), 0
    while d <= today:
        total += collect_dart(f'{d:%Y%m%d}', log)
        d += timedelta(days=1)
    return total


if __name__ == '__main__':
    collect_dart(sys.argv[1] if len(sys.argv) > 1 else None)

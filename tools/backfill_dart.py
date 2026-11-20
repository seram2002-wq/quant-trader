"""과거 DART 공시 목록 받기 (스윙 백테스트용, 기본 2011 ~ 2024)

    python tools/backfill_dart.py                         2011-01-01 ~ 2024-12-31, 요청 12,000번까지
    python tools/backfill_dart.py --max-calls 5000        요청 수를 더 줄여서
    python tools/backfill_dart.py 20150101 20151231       기간 지정

run.py가 장 마감 루틴까지 끝낸 뒤(15:35 이후)에 실행한다. 같은 DART_API_KEY를 쓴다.

- 주요사항보고서(B)와 거래소공시(I)만 받는다. 펀드·증권신고서 같은 유형을 빼서 요청이 절반 이하로 준다
  (2011 ~ 2024 평일 약 3,650일 × 하루 2 ~ 3번 ≈ 9,000번)
- data/dart/YYYYMMDD.csv에 하루씩 저장한다. 이미 있는 날짜는 건너뛰므로 끊겼다가 다시 실행하면 이어받는다
- 한 날짜의 B·I를 다 받아야 그 날짜 파일을 쓴다. 중간에 멈춘 날짜는 다음 실행 때 처음부터 다시 받는다
- 요청이 --max-calls에 닿거나, DART가 한도 초과(020)나 다른 오류를 돌려주거나, 연결이 끊기면 그 자리에서 멈춘다.
  다 받은 날짜는 이미 저장돼 있다. DART 하루 한도는 2만 번이라 기본 12,000번이면 run.py 몫이 남는다
- 주말은 공시 접수가 없어 건너뛴다 (2015-01-03 토요일 B·I·전체 모두 0건 확인)
- 과거 자료라 처음 본 시각(collected_at)은 비워 둔다. 백테스트에서는 접수일(rcept_dt) 다음 거래일부터 안 것으로 본다

주의: 이 파일들은 B·I 유형만 있다. run.py가 매일 모으는 파일(모든 유형, 2026-11-16 ~)과 기간이 겹치지 않는다.
"""
import csv
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools import collect_dart as cd           # noqa: E402  (API_URL, FIELDS, OUT_DIR, path_of 재사용)

TYPES = ('B', 'I')                              # 주요사항보고서, 거래소공시


class Stop(Exception):
    """요청 한도·DART 오류·연결 오류로 멈출 때"""


def backfill(api_key, start, end, max_calls=12000, log=print):
    """start ~ end(YYYYMMDD) 평일을 하루씩 받는다. (저장한 날짜 수, 쓴 요청 수, 멈춘 이유 또는 '')"""
    calls, saved = 0, 0

    def get(day, ty, page):
        nonlocal calls
        if calls >= max_calls:
            raise Stop(f'요청 {max_calls:,}번에 닿아 멈춤')
        calls += 1
        time.sleep(0.15)
        try:
            data = requests.get(cd.API_URL, timeout=15, params={
                'crtfc_key': api_key, 'bgn_de': day, 'end_de': day, 'pblntf_ty': ty,
                'page_no': page, 'page_count': 100}).json()
        except (requests.RequestException, ValueError) as ex:
            raise Stop(f'{day} {ty} 조회 오류 : {ex}')
        status = data.get('status')
        if status not in ('000', '013'):                 # 013 = 그날 공시 없음
            raise Stop(f'{day} {ty} DART 응답 {status} : {data.get("message", "")}')
        return data

    d, last = datetime.strptime(start, '%Y%m%d'), datetime.strptime(end, '%Y%m%d')
    cd.OUT_DIR.mkdir(parents=True, exist_ok=True)
    try:
        while d <= last:
            cur, d = d, d + timedelta(days=1)
            day = cur.strftime('%Y%m%d')
            if cur.weekday() >= 5 or cd.path_of(day).exists():      # 주말이거나 이미 받은 날
                continue
            rows = {}
            for ty in TYPES:
                page = 1
                while True:
                    data = get(day, ty, page)
                    for item in data.get('list') or []:
                        row = {k: (item.get(k) or '').strip() for k in cd.FIELDS}   # collected_at은 빈칸
                        rows[row['rcept_no']] = row
                    if page >= int(data.get('total_page') or 1):
                        break
                    page += 1
            tmp = cd.path_of(day).with_suffix('.tmp')
            with open(tmp, 'w', newline='', encoding='utf-8-sig') as f:
                w = csv.DictWriter(f, fieldnames=cd.FIELDS)
                w.writeheader()
                w.writerows(sorted(rows.values(), key=lambda r: r['rcept_no']))
            os.replace(tmp, cd.path_of(day))             # 날짜 파일은 다 받은 뒤에만 생긴다
            saved += 1
            if saved % 100 == 0:
                log(f'{day}까지 받음 (요청 {calls:,}번)')
    except Stop as ex:
        return saved, calls, str(ex)
    return saved, calls, ''


if __name__ == '__main__':
    args = sys.argv[1:]
    max_calls = int(args[args.index('--max-calls') + 1]) if '--max-calls' in args else 12000
    days = [a for a in args if a.isdigit() and len(a) == 8]
    start = days[0] if days else '20110101'
    end = days[1] if len(days) > 1 else '20241231'
    key = os.getenv('DART_API_KEY', '').strip()
    if not key:
        sys.exit('.env에 DART_API_KEY가 없습니다.')
    saved, calls, why = backfill(key, start, end, max_calls)
    print(f'저장 {saved}일, 요청 {calls:,}번. ' + (f'{why}. 다시 실행하면 이어받습니다.' if why else '끝까지 받았습니다.'))

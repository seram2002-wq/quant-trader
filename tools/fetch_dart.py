"""DART 재무제표 받기 (백테스트용 PBR, ROE, 이익 등)

    python tools/fetch_dart.py

.env에 DART_API_KEY (opendart.fss.or.kr에서 받은 인증키)가 있어야 한다.
받는 것 (data/research/dart/, git에 올리지 않음)
    corps.csv        회사 고유번호와 종목코드, 회사 이름
    accounts.csv     2015년~ 사업·분기·반기 보고서의 주요 계정
                     (자산총계, 부채총계, 자본총계, 매출액, 영업이익, 당기순이익)
                     rcept_no 앞 8자리가 공시한 날 → 그날 이후에만 쓸 수 있는 정보로 처리
한 번에 100개 회사씩 받아서 처음에는 약 1,500번 호출, 5~10분 걸린다 (하루 한도 2만 번).
중간에 끊겨도 다시 실행하면 받은 보고서는 건너뛴다.
"""
import io
import os
import sys
import time
import zipfile
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / '.env', override=True)

import pandas as pd                             # noqa: E402

OUT = ROOT / 'data' / 'research' / 'dart'
API = 'https://opendart.fss.or.kr/api/'
FIRST_YEAR = 2015                               # 다중회사 주요계정 API는 2015년 사업연도부터
REPORTS = {'11013': 'Q1', '11012': 'H1', '11014': 'Q3', '11011': 'FY'}
TOP_RANK = 600                                  # 백테스트 종목 범위(상위 200~300)보다 넉넉하게
CHUNK = 20                                      # 한 번에 보내는 회사 수
ACCOUNTS = ('자산총계', '부채총계', '자본총계', '매출액', '영업이익', '당기순이익')


def key():
    k = os.getenv('DART_API_KEY', '').strip()
    if not k:
        sys.exit('.env에 DART_API_KEY가 없습니다.')
    return k


def fetch_corps(k):
    """상장 회사 목록 (지금 상장된 회사만 종목코드가 있다)"""
    res = requests.get(API + 'corpCode.xml', params={'crtfc_key': k}, timeout=60)
    try:
        z = zipfile.ZipFile(io.BytesIO(res.content))
    except zipfile.BadZipFile:
        sys.exit(f'회사 목록을 받지 못했습니다: {res.text[:200]}')
    root = ET.fromstring(z.read(z.namelist()[0]))
    rows = [{'corp_code': e.findtext('corp_code'), 'corp_name': e.findtext('corp_name'),
             'stock_code': (e.findtext('stock_code') or '').strip(),
             'modify_date': e.findtext('modify_date')} for e in root.iter('list')]
    df = pd.DataFrame(rows)
    df.to_csv(OUT / 'corps.csv', index=False, encoding='utf-8-sig')
    print(f'회사 목록 {len(df):,}개 (종목코드 있는 회사 {(df.stock_code != "").sum():,}개)')
    return df


def matched_delisted(corps):
    """상장폐지된 회사: 거래소 시세(marcap)의 종목 이름과 DART 회사 이름이 같으면 연결"""
    sys.path.insert(0, str(ROOT))
    from trader import marcap
    names = {}
    for y in range(FIRST_YEAR, date.today().year + 1):
        p = marcap.path_of(y)
        if p.exists():
            df = pd.read_parquet(p, columns=['Code', 'Name'])
            names.update(zip(df['Code'], df['Name']))
    listed = set(corps.loc[corps.stock_code != '', 'stock_code'])
    no_code = corps[corps.stock_code == ''].drop_duplicates('corp_name', keep=False)
    by_name = dict(zip(no_code.corp_name, no_code.corp_code))
    extra = {code: by_name[name] for code, name in names.items()
             if code not in listed and code.endswith('0') and name in by_name}
    print(f'상장폐지 등으로 종목코드가 빠진 회사 중 이름으로 연결 {len(extra):,}개')
    return extra


def request(k, chunk, year, code, stats):
    """여러 회사를 한 번에 요청. 응답이 이상하면 반으로 나눠 다시, 한 회사도 안 되면 건너뜀"""
    try:
        res = requests.get(API + 'fnlttMultiAcnt.json', timeout=30, params={
            'crtfc_key': k, 'corp_code': ','.join(chunk), 'bsns_year': str(year), 'reprt_code': code})
        data = res.json()
    except (requests.RequestException, ValueError):
        data = None
    finally:
        time.sleep(0.15)
    status = data.get('status') if data else '응답 오류'
    stats[status] = stats.get(status, 0) + 1
    if status == '020':
        sys.exit('오늘 호출 한도를 넘었습니다. 내일 다시 실행하세요.')
    if status in ('010', '011', '012', '901'):
        sys.exit(f'DART 오류 {status} {data.get("message")} (인증키 확인)')
    if status == '000':
        return data.get('list', []) or []
    if status == '013':
        return []
    if len(chunk) == 1:
        return []
    half = len(chunk) // 2
    return request(k, chunk[:half], year, code, stats) + request(k, chunk[half:], year, code, stats)


def fetch_accounts(k, targets):
    """targets: {corp_code: stock_code}"""
    path = OUT / 'accounts.csv'
    done = set()
    if path.exists():
        old = pd.read_csv(path, dtype=str, usecols=['bsns_year', 'reprt_code', 'corp_code'])
        done = set(zip(old.bsns_year, old.reprt_code, old.corp_code))
    tried_file = OUT / 'tried.txt'
    tried = set(tried_file.read_text().split()) if tried_file.exists() else set()
    corps = sorted(targets)
    this_year = date.today().year
    calls = 0
    for year in range(FIRST_YEAR, this_year + 1):
        for code, label in REPORTS.items():
            todo = [c for c in corps if (str(year), code, c) not in done
                    and f'{year}_{code}_{c}' not in tried]
            if not todo:
                continue
            rows = []
            stats = {}
            for i in range(0, len(todo), CHUNK):
                chunk = todo[i:i + CHUNK]
                for r in request(k, chunk, year, code, stats):
                    name = (r.get('account_nm') or '').split('(')[0].strip()
                    if name in ACCOUNTS and r.get('sj_div') in ('BS', 'IS', 'CIS'):
                        r['account_nm'] = name
                        rows.append({k2: r.get(k2) for k2 in (
                            'corp_code', 'stock_code', 'bsns_year', 'reprt_code', 'rcept_no',
                            'fs_div', 'sj_div', 'account_nm', 'thstrm_amount', 'thstrm_add_amount')})
                if year < this_year - 1:         # 최근 보고서는 나중에 공시될 수 있어 다음에 다시 확인
                    tried.update(f'{year}_{code}_{c}' for c in chunk)
            calls += sum(stats.values())
            if rows:
                df = pd.DataFrame(rows)
                df['stock_code'] = df['corp_code'].map(targets)
                df.to_csv(path, mode='a', header=not path.exists(), index=False, encoding='utf-8-sig')
            tried_file.write_text('\n'.join(sorted(tried)))
            detail = ', '.join(f'{k2} {v}' for k2, v in stats.items())
            print(f'  {year} {label} : {len(rows):,}줄 (누적 호출 {calls}번 / {detail})', flush=True)


def top_codes(rank_limit=TOP_RANK):
    """2015년 이후 어느 달 말이든 시가총액 rank_limit위 안에 든 적이 있는 보통주 (상장폐지 포함)"""
    sys.path.insert(0, str(ROOT))
    from trader import marcap
    codes = set()
    for y in range(FIRST_YEAR, date.today().year + 1):
        p = marcap.path_of(y)
        if not p.exists():
            continue
        df = pd.read_parquet(p, columns=['Date', 'Code', 'Market', 'Marcap'])
        df = df[df['Market'].isin(marcap.MARKETS) & df['Code'].str.endswith('0')]
        df['Date'] = pd.to_datetime(df['Date'])
        ends = df.groupby(df['Date'].dt.to_period('M'))['Date'].transform('max')
        df = df[df['Date'] == ends]
        df['rank'] = df.groupby('Date')['Marcap'].rank(ascending=False)
        codes |= set(df.loc[df['rank'] <= rank_limit, 'Code'])
    return codes


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    k = key()
    corps = fetch_corps(k)
    wanted = top_codes()
    has = corps[corps.stock_code.isin(wanted)].drop_duplicates('stock_code')
    targets = dict(zip(has.corp_code, has.stock_code))
    print(f'시가총액 {TOP_RANK}위 안에 든 적이 있는 종목 {len(wanted):,}개 중 DART 회사와 연결 {len(targets):,}개')
    fetch_accounts(k, targets)
    print('끝났습니다.')


if __name__ == '__main__':
    main()

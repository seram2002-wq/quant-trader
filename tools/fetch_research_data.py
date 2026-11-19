"""백테스트용 과거 데이터 받기 (한 번 받고, 이후에는 새로 생긴 달만 받음)

    python tools/fetch_research_data.py

받는 것 (모두 data/ 아래, git에 올리지 않음)
    1. 거래소 전 종목 일별 시세 2010년~     data/marcap/           (FinanceData marcap, 로그인 불필요)
       지금 상장 종목의 업종                 data/research/sector.csv
    2. 월말 전 종목 PER·PBR·배당수익률      data/research/fundamental/YYYYMMDD.csv
    3. 월별 종목별 외국인·기관 순매수 금액   data/research/flow/YYYYMM_외국인.csv, YYYYMM_기관합계.csv
    4. KODEX 200, KODEX 인버스 장중 시세    data/research/intraday/   (야후 파이낸스, 5분봉 60일·1시간봉 2년)

2, 3은 한국거래소 정보데이터시스템(data.krx.co.kr) 로그인이 필요하다.
회원 가입(무료) 후 .env에 KRX_ID, KRX_PW를 적는다. 없으면 그 부분만 건너뛴다.
처음에는 10~20분 걸린다. 중간에 끊겨도 다시 실행하면 받은 파일은 건너뛴다.
"""
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / '.env', override=True)       # pykrx가 import될 때 KRX_ID, KRX_PW를 읽으므로 먼저

import pandas as pd                             # noqa: E402
from trader import marcap                       # noqa: E402

OUT = ROOT / 'data' / 'research'
FIRST_YEAR = 2010
FIRST_MONTH = '2013-01'                          # 재무·수급은 이 달부터 (탐색 구간 2015년~에 여유)
INVESTORS = ['외국인', '기관합계']


def month_ends():
    """marcap 거래일로 달마다 (첫 거래일, 마지막 거래일)"""
    days = []
    for y in range(int(FIRST_MONTH[:4]), pd.Timestamp.today().year + 1):
        days += list(pd.read_parquet(marcap.path_of(y), columns=['Date'])['Date'].unique())
    s = pd.Series(sorted(pd.to_datetime(days)))
    s = s[s >= FIRST_MONTH]
    g = s.groupby(s.dt.strftime('%Y-%m'))
    return [(m, v.min().strftime('%Y%m%d'), v.max().strftime('%Y%m%d')) for m, v in g]


def fetch_marcap():
    print('\n[1/4] 거래소 전 종목 일별 시세, 업종')
    marcap.update(range(FIRST_YEAR, pd.Timestamp.today().year + 1))
    fetch_sectors()
    print('완료')


def fetch_sectors():
    """지금 상장 종목의 업종 (FinanceData가 매일 올리는 거래소 상장 목록). 백테스트 업종 중립에 사용"""
    import requests
    url = 'https://raw.githubusercontent.com/FinanceData/fdr_krx_data_cache/refs/heads/master/data/listing/desc/{}.csv'
    OUT.mkdir(parents=True, exist_ok=True)
    for back in range(0, 15):                    # 가장 최근 날짜 파일을 찾는다
        day = (pd.Timestamp.today() - pd.Timedelta(days=back)).strftime('%Y-%m-%d')
        try:
            res = requests.get(url.format(day), timeout=30)
        except requests.RequestException:
            continue
        if res.status_code == 200:
            (OUT / 'sector.csv').write_bytes(res.content)
            print(f'업종 목록 받음 ({day})')
            return
    print('업종 목록을 찾지 못했습니다 (업종 없이도 백테스트는 됩니다)')


def fetch_krx(months):
    print('\n[2/4, 3/4] 월말 PER·PBR·배당, 월별 외국인·기관 순매수 (한국거래소)')
    if not (os.getenv('KRX_ID') and os.getenv('KRX_PW')):
        print('.env에 KRX_ID, KRX_PW가 없어서 건너뜁니다.')
        return
    try:
        from pykrx import stock
        from pykrx.website.comm import auth
    except ImportError:
        print('pykrx가 없습니다: pip install -r requirements.txt')
        return
    if auth.get_auth_session() is None:
        print('한국거래소 로그인이 안 되어 건너뜁니다 (python tools/krx_login_check.py 로 확인).')
        return
    fdir, qdir = OUT / 'fundamental', OUT / 'flow'
    fdir.mkdir(parents=True, exist_ok=True)
    qdir.mkdir(parents=True, exist_ok=True)
    this_month = pd.Timestamp.today().strftime('%Y-%m')
    for n, (m, first, last) in enumerate(months, 1):
        if m == this_month:
            continue                             # 아직 끝나지 않은 달은 받지 않음
        jobs = [(fdir / f'{last}.csv', lambda: stock.get_market_fundamental(last, market='ALL'))]
        for inv in INVESTORS:
            jobs.append((qdir / f'{m.replace("-", "")}_{inv}.csv',
                         lambda inv=inv: stock.get_market_net_purchases_of_equities(first, last, 'ALL', inv)))
        for path, job in jobs:
            if path.exists():
                continue
            for attempt in range(3):
                try:
                    df = job()
                    break
                except Exception as ex:                  # 사이트 응답 오류는 잠시 뒤 다시
                    print(f'  {path.name} 실패 ({ex}), 다시 시도')
                    time.sleep(3)
            else:
                print(f'  {path.name} 건너뜀')
                continue
            if df is None or df.empty:
                print(f'  {path.name} : 빈 결과 (로그인 실패이거나 자료 없음)')
                continue
            df.index.name = 'ticker'
            df.to_csv(path, encoding='utf-8-sig')
            time.sleep(0.5)
        print(f'  {m} 완료 ({n}/{len(months)})', flush=True)


def fetch_intraday():
    print('\n[4/4] KODEX 200, KODEX 인버스 장중 시세 (야후 파이낸스)')
    try:
        import yfinance as yf
    except ImportError:
        print('yfinance가 없습니다: pip install -r requirements.txt')
        return
    d = OUT / 'intraday'
    d.mkdir(parents=True, exist_ok=True)
    for code in ('069500', '114800'):
        for interval, period in (('5m', '60d'), ('60m', '730d'), ('1d', 'max')):
            try:
                df = yf.download(f'{code}.KS', interval=interval, period=period,
                                 auto_adjust=False, progress=False, multi_level_index=False)
            except Exception as ex:
                print(f'  {code} {interval} 실패 ({ex})')
                continue
            path = d / f'{code}_{interval}.csv'
            if path.exists():                    # 예전에 받은 것과 합쳐서 기간을 늘려 감
                old = pd.read_csv(path, index_col=0, parse_dates=True)
                df = pd.concat([old, df]).loc[lambda x: ~x.index.duplicated(keep='last')].sort_index()
            df.to_csv(path, encoding='utf-8-sig')
            print(f'  {code} {interval} : {len(df):,}줄 ({df.index.min()} ~ {df.index.max()})')


def main():
    fetch_marcap()
    fetch_krx(month_ends())
    fetch_intraday()
    print('\n모두 끝났습니다.')


if __name__ == '__main__':
    main()

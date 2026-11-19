"""한국거래소 전 종목 일별 시세 (FinanceData/marcap 데이터셋)

https://github.com/FinanceData/marcap
    1995년부터 매일 전 종목(상장폐지 종목 포함)의 시세, 거래대금, 시가총액, 소속부를
    연도별 파일(marcap-YYYY.parquet, 한 해 약 20MB)로 공개하고 매일 자동 갱신한다.
    거래소 발표보다 보통 1~2거래일 늦다.

data/marcap/에 내려받아 두고, 멀티팩터 전략(장중)과 backtest.py가 같이 쓴다.
가격(Close)은 수정 전 가격이라 액면분할 날에 크게 뛴다. 수익률은 거래소가 계산한
등락률(ChangesRatio, 액면분할 반영)을 이어 붙여서 구한다 (adj_index).
현금 배당은 반영되지 않는다 (배당락 날 그만큼 수익률이 낮게 잡힘).
"""
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

DATA_DIR = Path(__file__).resolve().parent.parent / 'data' / 'marcap'
URL = 'https://raw.githubusercontent.com/FinanceData/marcap/master/data/marcap-{year}.parquet'
COLUMNS = ['Date', 'Code', 'Name', 'Market', 'Dept', 'Close', 'ChangesRatio',
           'Volume', 'Amount', 'Marcap']
MARKETS = ('KOSPI', 'KOSDAQ', 'KOSDAQ GLOBAL')     # 코넥스 제외


def path_of(year):
    return DATA_DIR / f'marcap-{year}.parquet'


def update(years, log=print):
    """필요한 연도 파일을 내려받는다. 올해 파일은 오늘 받은 적이 없으면 다시 받는다.

    받기에 실패해도 예전 파일이 있으면 그대로 쓰고, 없으면 OSError를 일으킨다.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    this_year = date.today().year
    for year in years:
        p = path_of(year)
        fresh = p.exists() and (year < this_year or
                                datetime.fromtimestamp(p.stat().st_mtime).date() == date.today())
        if fresh:
            continue
        try:
            t = time.time()
            res = requests.get(URL.format(year=year), timeout=60)
            res.raise_for_status()
            tmp = p.with_suffix('.tmp')
            tmp.write_bytes(res.content)
            tmp.replace(p)
            log(f'marcap-{year} 받음 ({len(res.content) / 1e6:.0f}MB, {time.time() - t:.0f}초)')
        except (requests.RequestException, OSError) as ex:
            if p.exists():
                log(f'marcap-{year} 갱신 실패, 이전 파일 사용 ({ex})')
            else:
                raise OSError(f'marcap-{year} 받기 실패 : {ex}')


def load(start, end=None, log=print):
    """start~end 기간의 전 종목 일별 시세 (긴 표). start, end: 'YYYY-MM-DD'"""
    import pandas as pd
    end = end or date.today().isoformat()
    years = range(int(start[:4]), int(end[:4]) + 1)
    update(years, log)
    frames = []
    for y in years:
        df = pd.read_parquet(path_of(y), columns=COLUMNS)
        df = df[(df['Date'] >= start) & (df['Date'] <= end)]
        frames.append(df)
    df = pd.concat(frames, ignore_index=True)
    df['Date'] = pd.to_datetime(df['Date'])
    return df.sort_values(['Date', 'Code'], ignore_index=True)


def eligible(df):
    """보통주만: 코스피·코스닥, 우선주(코드 끝자리가 0이 아님), 스팩, 관리종목,
    투자주의환기종목, 거래 없는 날 제외"""
    dept = df['Dept'].fillna('')
    return (df['Market'].isin(MARKETS)
            & df['Code'].str[-1].eq('0')
            & ~dept.str.contains('관리|SPAC|환기')
            & ~df['Name'].fillna('').str.contains('스팩')
            & (df['Volume'] > 0))


def wide(df, column):
    """날짜 × 종목 표"""
    return df.pivot(index='Date', columns='Code', values=column)


def adj_index(df):
    """등락률을 이어 붙인 수정 가격 지수 (날짜 × 종목). 두 날짜의 비율이 그 사이 수익률"""
    ratio = wide(df, 'ChangesRatio')
    listed = wide(df, 'Close').notna()
    return (1 + ratio.fillna(0) / 100).cumprod().where(listed)


def start_for(trading_days, today=None):
    """trading_days 거래일을 넉넉히 덮는 시작 날짜"""
    today = today or date.today()
    return (today - timedelta(days=int(trading_days * 1.5) + 20)).isoformat()

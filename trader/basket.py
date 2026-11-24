"""업종별 대장주 바구니: 장 마감 반전 v3와 알파 마이너가 같이 쓰는 종목 범위

    python -m trader.basket            지난달 말 기준 바구니를 만든다 (이미 있으면 건너뜀)
    python -m trader.basket 202610     2026년 10월 말 기준으로 만든다

선정 (종목 이름이 아니라 규칙. 백테스트도 같은 규칙을 그 시점 자료로)
    기준일   : 매월 마지막 거래일 종가. 다음 달 둘째 거래일부터 적용 (자료가 1 ~ 2일 늦게 오는 것 반영)
    보통주   : 코스피·코스닥, 종목코드 끝자리 0, 관리·스팩·투자주의환기 제외 (marcap.eligible),
               이름에 스팩·리츠·인프라·ETF·ETN·우선주 표시가 있으면 제외
    거래     : 기준일까지 최근 60거래일 모두 정상 거래 (신규 상장·거래정지 이력 제외)
    유동성   : 최근 20거래일 평균 거래대금 100억 원 이상
    업종     : 산업 분류(KSIC) 문구 → 12개 업종 (SECTORS). config.SECTOR_OVERRIDE가 먼저
    지주사   : '기타 금융업' 중 금융지주·카드·캐피탈만 금융에 남기고 나머지 제외. config.HOLDING_EXCLUDE_LIST 제외
    순위     : 업종 안에서 시가총액 상위 3종목. 3개가 안 되는 업종은 있는 만큼
data/universe/basket_YYYYMMDD.csv (YYYYMMDD = 기준일)에 저장. 산업 분류는 지금 기준(sector.csv)이라
과거 시점의 업종 변경과 상장폐지 종목의 업종은 반영되지 않는다.
"""
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

import config
from trader import marcap

DIR = Path(__file__).resolve().parent.parent / 'data' / 'universe'
SECTOR_FILE = Path(__file__).resolve().parent.parent / 'data' / 'research' / 'sector.csv'
TOP, MIN_AMOUNT20, DAYS = 3, 1e10, 60

# 업종: 산업 분류 문구에 들어 있는 말 (위에서부터 먼저 맞는 것)
SECTORS = [
    ('반도체', ['반도체 제조업', '특수 목적용 기계']),
    ('IT 하드웨어·전자부품', ['전자부품', '통신 및 방송 장비', '컴퓨터 및 주변', '측정, 시험', '영상 및 음향', '기타 전기장비']),
    ('2차전지·화학', ['전지 제조업', '기초 화학물질', '석유 정제품', '합성고무', '비료']),
    ('자동차·부품', ['자동차', '고무제품']),
    ('조선·기계·방산', ['선박', '항공기', '무기', '일반 목적용 기계', '그외 기타 운송장비', '전동기, 발전기', '절연선',
                    '구조용 금속']),
    ('철강·소재', ['1차 철강', '1차 비철금속', '비금속 광물', '시멘트', '금속 가공']),
    ('바이오·제약', ['의약', '자연과학 및 공학 연구', '의료용']),
    ('인터넷·게임·소프트웨어', ['자료처리', '소프트웨어', '컴퓨터 프로그래밍', '오디오물 출판', '영화', '방송업']),
    ('금융', ['기타 금융업', '보험', '금융 지원 서비스', '은행', '신탁']),
    ('통신·유틸리티', ['전기 통신', '전기업', '가스', '증기']),
    ('건설', ['건물 건설', '토목 건설', '건축기술', '전문직별 공사']),
    ('소비재', ['기타 화학제품', '식품', '음료', '담배', '종합 소매', '개인 서비스', '상품 종합 도매', '의복']),
]
# 간밤 미국 ETF (연결이 강함·중간인 업종만). 모든 종목에 SPY, QQQ도 같이 기록
SECTOR_US = {'반도체': 'SOXX', 'IT 하드웨어·전자부품': 'SOXX', '2차전지·화학': 'LIT', '철강·소재': 'SLX',
             '바이오·제약': 'XBI'}
US_EXCHANGE = {'SOXX': 'NAS', 'LIT': 'AMS', 'XBI': 'AMS', 'SLX': 'AMS', 'SPY': 'AMS', 'QQQ': 'NAS'}
NAME_EXCLUDE = re.compile(r'스팩|리츠|인프라|ETF|ETN|\d우[A-Z]?$|우B$|우\(전환\)$')
FINANCE_NAME = re.compile(r'금융|카드|캐피탈')


def sector_of(name, industry, products):
    """12개 업종 중 하나 또는 None (해당 없음·지주사)"""
    if name in config.SECTOR_OVERRIDE:
        return config.SECTOR_OVERRIDE[name]
    if name in config.HOLDING_EXCLUDE_LIST:
        return None
    industry, products = str(industry), str(products)
    if '기타 금융업' in industry:                       # 금융지주·카드·캐피탈만 (신한지주처럼 이름에 없으면 사업 내용으로)
        fin = FINANCE_NAME.search(name) or ('금융지주' in products and '비금융' not in products)
        return '금융' if fin else None
    for sector, words in SECTORS:
        if any(w in industry for w in words):
            return sector
    return None


def select(df, sectors, base):
    """df: marcap 긴 표 (기준일 base까지 60거래일 이상), sectors: {code: (industry, products)}.
    업종별 상위 3종목 표 (sector, rank, code, name, mcap, amount20)"""
    df = df[df['Date'] <= base]
    days = sorted(df['Date'].unique())[-DAYS:]
    recent = df[df['Date'].isin(days)]
    full = recent[marcap.eligible(recent)].groupby('Code').size()
    a20 = recent[recent['Date'].isin(days[-20:])].groupby('Code')['Amount'].mean()
    x = df[(df['Date'] == days[-1]) & marcap.eligible(df)].set_index('Code')
    x = x[(full.reindex(x.index) == DAYS) & (a20.reindex(x.index) >= MIN_AMOUNT20)
          & ~x['Name'].fillna('').str.contains(NAME_EXCLUDE)]
    x = x.assign(amount20=a20.reindex(x.index),
                 sector=[sector_of(n, *sectors.get(c, ('', ''))) for c, n in zip(x.index, x['Name'])])
    x = x.dropna(subset=['sector']).sort_values('Marcap', ascending=False)
    x['rank'] = x.groupby('sector').cumcount() + 1
    x = x[x['rank'] <= TOP].reset_index()
    return x.rename(columns={'Code': 'code', 'Name': 'name', 'Marcap': 'mcap'})[
        ['sector', 'rank', 'code', 'name', 'mcap', 'amount20']].sort_values(['sector', 'rank'], ignore_index=True)


def trading_day_after(day, n):
    """day(date) 다음 n번째 평일 (config.HOLIDAYS 제외)"""
    while n:
        day += timedelta(days=1)
        if day.weekday() < 5 and day.strftime('%Y%m%d') not in config.HOLIDAYS:
            n -= 1
    return day


def build(year, month, log=print):
    """year-month 마지막 거래일 기준 바구니를 만들어 저장. 그달 자료가 아직 다 없으면 None"""
    first_next = date(year + month // 12, month % 12 + 1, 1)
    df = marcap.load((first_next - timedelta(days=130)).isoformat(), log=log)
    if df['Date'].max() < pd.Timestamp(first_next):        # 다음 달 자료가 하나도 없으면 그달 말이 확정 안 됨
        log(f'{year}-{month:02d} 말 자료가 아직 없습니다 (마지막 {df["Date"].max():%Y-%m-%d})')
        return None
    base = df[df['Date'] < pd.Timestamp(first_next)]['Date'].max()
    s = pd.read_csv(SECTOR_FILE, dtype={'Code': str})
    out = select(df, {c: (i, p) for c, i, p in zip(s['Code'], s['Industry'], s['Products'])}, base)
    out['us_etf'] = out['sector'].map(SECTOR_US).fillna('')
    out.insert(0, 'base', base.strftime('%Y%m%d'))
    out.insert(1, 'effective_from', trading_day_after(base.date(), 2).strftime('%Y%m%d'))
    DIR.mkdir(parents=True, exist_ok=True)
    path = DIR / f'basket_{base:%Y%m%d}.csv'
    out.to_csv(path, index=False, encoding='utf-8')
    log(f'바구니 {len(out)}종목 ({out["sector"].nunique()}개 업종), {base:%Y-%m-%d} 기준, '
        f'{out["effective_from"].iloc[0]}부터 → {path.name}')
    return out


def history(start, end, log=print):
    """연구용: start ~ end('YYYY-MM-DD') 사이 매월 마지막 거래일 기준 바구니 (select와 같은 규칙).
    표 하나 (base 열 = 기준일). 끝 달은 그달 자료가 다 있어야 하므로 end는 지난 연말 등 확정된 날짜로"""
    s = pd.read_csv(SECTOR_FILE, dtype={'Code': str})
    sectors = {c: (i, p) for c, i, p in zip(s['Code'], s['Industry'], s['Products'])}
    out = []
    for year in range(int(start[:4]), int(end[:4]) + 1):
        df = marcap.load(f'{year - 1}-08-01', f'{year}-12-31', log=lambda *_: None)
        d = df['Date']
        for base in d[(d >= start) & (d <= end) & (d.dt.year == year)].groupby(d.dt.month).max():
            out.append(select(df, sectors, base).assign(base=base))
        log(f'{year}년까지 바구니 {len(out)}개월')
    return pd.concat(out, ignore_index=True)


def ensure(today=None, log=print):
    """지난달 말 바구니가 없으면 만든다 (자료가 아직 없으면 다음에 다시)"""
    today = today or date.today()
    y, m = (today.year, today.month - 1) if today.month > 1 else (today.year - 1, 12)
    if any(DIR.glob(f'basket_{y}{m:02d}*.csv')):
        return
    build(y, m, log)


def load(day=None):
    """day('YYYYMMDD')에 적용되는 바구니 (적용일이 day 이전인 것 중 가장 최근). 없으면 None"""
    day = day or datetime.now().strftime('%Y%m%d')
    best = None
    for path in sorted(DIR.glob('basket_*.csv')):
        b = pd.read_csv(path, dtype={'code': str, 'base': str, 'effective_from': str})
        if len(b) and b['effective_from'].iloc[0] <= day:
            best = b
    return best


if __name__ == '__main__':
    if len(sys.argv) > 1:
        build(int(sys.argv[1][:4]), int(sys.argv[1][4:6]))
    else:
        ensure()

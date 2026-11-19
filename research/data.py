"""백테스트용 데이터 (날짜 × 종목 표)

    from research.data import load_panel
    p = load_panel('2010-01-01')          # 2010년부터 오늘까지

p는 Panel 객체로, 아래 표(pandas DataFrame, 행 = 거래일, 열 = 종목코드)를 갖는다.
    p.close      종가 (수정 전)
    p.idx        수정 가격 지수 (거래소 등락률을 이어 붙인 것, 액면분할 반영). 수익률 계산은 이걸로
    p.ret        일별 수익률
    p.open       시가 (수정 전)
    p.amount     거래대금 (원)
    p.amount20   20일 평균 거래대금
    p.mcap       시가총액 (원)
    p.volume     거래량
    p.eligible   보통주이고 거래가 있는 날 True (우선주, 스팩, 관리종목, 투자주의환기, 코넥스 제외)
    p.kospi      코스피 전 종목 시가총액 가중 지수 (직접 계산, Series)
    p.sector     종목코드 → 넓은 업종 이름 (dict, 14개 업종)
    p.names      종목코드 → 이름 (dict)

재무(DART)와 거래소 수급·배당은 따로 불러서 붙인다:
    p.add_dart()   → p.dart['equity'], ['assets'], ['liabilities'], ['sales_ttm'], ['op_ttm'], ['ni_ttm']
    p.add_krx()    → p.krx['per'], ['pbr'], ['div'], ['foreign'], ['institution'] (직전 1개월 순매수 금액),
                     ['foreign3'], ['institution3'] (직전 3개월 합)
모두 공시일·발표일 다음 거래일부터 값이 들어간다 (미래 정보 없음).

데이터는 먼저 받아 둔다:
    python tools/fetch_research_data.py   (일별 시세, 업종, 거래소 계정이 있으면 수급·배당)
    python tools/fetch_dart.py            (DART 재무, DART_API_KEY 필요)
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from trader import marcap                       # noqa: E402

RESEARCH = ROOT / 'data' / 'research'
SECTOR_FILE = RESEARCH / 'sector.csv'

# 표준산업분류 이름 → 넓은 업종 (위에서부터 먼저 맞는 것)
SECTOR_RULES = [
    ('IT·인터넷·미디어', ['소프트웨어', '컴퓨터 프로그래밍', '정보 서비스', '자료처리', '출판', '영화', '방송', '광고', '전기 통신', '오디오', '게임']),
    ('금융', ['금융', '보험', '신탁', '은행', '회사 본부']),
    ('제약·바이오', ['의약', '의료', '자연과학 및 공학 연구']),
    ('전기·전자', ['반도체', '전자부품', '컴퓨터 및 주변', '영상 및 음향', '통신 및 방송 장비', '측정', '사진장비', '전기장비', '전동기', '전지', '절연선']),
    ('자동차', ['자동차']),
    ('기계·조선·방산', ['기계', '선박', '항공기', '구조용 금속', '무기']),
    ('화학', ['화학', '플라스틱', '고무', '석유 정제']),
    ('소재', ['철강', '금속', '비철', '시멘트', '유리', '펄프', '종이', '비금속']),
    ('건설·부동산', ['건설', '부동산', '건축기술', '엔지니어링']),
    ('운송', ['운송', '해운', '창고', '항공 여객']),
    ('에너지·유틸리티', ['전기업', '가스', '증기', '발전']),
    ('음식료·생활', ['식품', '음료', '사료', '담배', '생활용품']),
    ('유통·소비', ['도매', '소매', '의복', '섬유', '신발', '가죽', '숙박', '음식점', '여행', '오락', '스포츠', '교육', '가구']),
]


def broad_sector(industry):
    s = str(industry)
    for name, words in SECTOR_RULES:
        if any(w in s for w in words):
            return name
    return '기타'


def load_sectors():
    """지금 상장 종목의 업종 (과거 상장폐지 종목은 없음 → 업종 모름으로 처리)"""
    if not SECTOR_FILE.exists():
        print('업종 파일이 없습니다 (python tools/fetch_research_data.py). 업종 없이 진행합니다.')
        return {}
    d = pd.read_csv(SECTOR_FILE, dtype={'Code': str})
    return {c: broad_sector(i) for c, i in zip(d['Code'], d['Industry'])}


class Panel:
    def __init__(self, start, end=None):
        end = end or pd.Timestamp.today().strftime('%Y-%m-%d')
        years = range(int(start[:4]), int(end[:4]) + 1)
        marcap.update(years)
        cols = ['Date', 'Code', 'Name', 'Market', 'Dept', 'Open', 'Close', 'ChangesRatio',
                'Volume', 'Amount', 'Marcap']
        keys = {'ratio': 'ChangesRatio', 'close': 'Close', 'open': 'Open', 'amount': 'Amount',
                'volume': 'Volume', 'mcap': 'Marcap', 'elig': 'elig', 'kmc': 'kmc'}
        parts = {k: [] for k in keys}
        self.names = {}
        for y in years:                                   # 한 해씩 읽어 메모리를 아낀다
            df = pd.read_parquet(marcap.path_of(y), columns=cols)
            df['Date'] = pd.to_datetime(df['Date'])
            df = df[(df['Date'] >= start) & (df['Date'] <= end)].drop_duplicates(['Date', 'Code'])
            if df.empty:
                continue
            df['elig'] = marcap.eligible(df).astype('float32')
            df['kmc'] = df['Marcap'].where(df['Market'].eq('KOSPI'))
            self.names.update(zip(df['Code'], df['Name']))
            for k, col in keys.items():
                parts[k].append(df.pivot(index='Date', columns='Code', values=col).astype('float32'))
            print(f'{y} 읽음', flush=True)
        w = {k: pd.concat(v).sort_index() for k, v in parts.items()}
        codes = w['close'].columns
        w = {k: v.reindex(columns=codes) for k, v in w.items()}
        listed = w['close'].notna()
        self.close, self.open, self.amount = w['close'], w['open'], w['amount']
        self.volume, self.mcap = w['volume'].fillna(0), w['mcap']
        self.ret = (w['ratio'] / 100).astype('float32')
        self.idx = (1 + self.ret.fillna(0).astype('float64')).cumprod().where(listed)
        self.amount20 = self.amount.rolling(20, min_periods=15).mean()
        self.eligible = w['elig'].fillna(0) == 1
        wgt = w['kmc'].shift(1)
        kr = (wgt * self.ret).sum(axis=1) / wgt.where(self.ret.notna()).sum(axis=1)
        self.kospi = (1 + kr.fillna(0)).cumprod()
        self.dates, self.codes = self.close.index, codes
        self.sector = load_sectors()
        self.dart, self.krx = {}, {}

    # ------------------------------------------------------------ 보조
    def daily_from_events(self, when, codes, values, max_age=400):
        """(발표일, 종목, 값) 목록 → 날짜 × 종목 표. 발표 다음 거래일부터, max_age 거래일까지 유지"""
        e = pd.DataFrame({'when': pd.to_datetime(when), 'code': codes, 'v': values}).dropna(subset=['when'])
        pos = self.dates.searchsorted(e['when'].values, side='right')
        e = e[pos < len(self.dates)].assign(avail=self.dates[pos[pos < len(self.dates)]])
        e = e.drop_duplicates(['code', 'avail'], keep='last')
        m = e.pivot(index='avail', columns='code', values='v')
        return m.reindex(index=self.dates, columns=self.codes).ffill(limit=max_age)

    def add_dart(self):
        """DART 재무 (data/research/dart/accounts.csv). 손익은 최근 4분기 합"""
        from trader import fundamentals as fu
        if not fu.ACCOUNTS_FILE.exists():
            print('DART 파일이 없습니다 (python tools/fetch_dart.py)')
            return self
        ev = fu.load_events()
        for c in ('assets', 'liabilities', 'equity', 'sales_ttm', 'op_ttm', 'ni_ttm'):
            self.dart[c] = fu.daily(ev, c, self.dates, self.codes)
        print('DART 재무 준비', flush=True)
        return self

    def add_krx(self):
        """거래소 월말 PER·PBR·배당수익률, 월별 외국인·기관 순매수 (data/research/fundamental, flow)"""
        fdir, qdir = RESEARCH / 'fundamental', RESEARCH / 'flow'
        if not fdir.exists() or not any(fdir.glob('*.csv')):
            print('거래소 자료가 없습니다 (.env에 KRX_ID, KRX_PW 넣고 python tools/fetch_research_data.py)')
            return self
        fr = []
        for f in sorted(fdir.glob('*.csv')):
            d = pd.read_csv(f, dtype={'ticker': str})
            d['when'] = pd.to_datetime(f.stem)
            fr.append(d)
        fu_ = pd.concat(fr)
        for col, key in (('PER', 'per'), ('PBR', 'pbr'), ('DIV', 'div')):
            self.krx[key] = self.daily_from_events(fu_['when'], fu_['ticker'], fu_[col], max_age=70)
        fr = []
        for f in sorted(qdir.glob('*.csv')):
            month, inv = f.stem.split('_')
            d = pd.read_csv(f, dtype={'ticker': str})[['ticker', '순매수거래대금']]
            d['when'] = pd.to_datetime(month + '01') + pd.offsets.MonthEnd(0)
            d['inv'] = inv
            fr.append(d)
        fl = pd.concat(fr)
        for inv, key in (('외국인', 'foreign'), ('기관합계', 'institution')):
            x = fl[fl['inv'] == inv]
            self.krx[key] = self.daily_from_events(x['when'], x['ticker'], x['순매수거래대금'], max_age=70)
            m = x.pivot_table(index='when', columns='ticker', values='순매수거래대금', aggfunc='sum').sort_index()
            m3 = m.rolling(3, min_periods=3).sum().stack().rename('v').reset_index()
            self.krx[key + '3'] = self.daily_from_events(m3['when'], m3['ticker'], m3['v'], max_age=70)
        print('거래소 수급·배당 준비', flush=True)
        return self


def load_panel(start='2010-01-01', end=None):
    return Panel(start, end)

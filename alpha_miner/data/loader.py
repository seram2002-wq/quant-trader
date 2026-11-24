"""research.data의 패널을 알파 수식용 피처(날짜 x 종목 DataFrame)로 바꾼다

가격은 액면분할을 반영한 수정 가격. 종목마다 처음 나온 날의 실제 종가에 맞춰 둔다
(그 뒤 분할이 있어도 이어지고, 종목끼리 가격 수준도 대략 비교할 수 있음. 앞으로의 값은 쓰지 않음).
거래량은 같은 계수로 나눠 분할 전후가 이어지게 한다. 거래대금은 그대로.

거래소 자료 (research Panel.add_krx, 2013-01 ~, 월말 발표 다음 거래일부터 한 달 동안 같은 값)
    per, pbr  : 월말 PER·PBR. 0(적자·자본잠식 등 의미 없음)은 빈칸으로
    div       : 배당수익률(%)
    foreign, institution    : 직전 1개월 외국인·기관 순매수 금액(원)
    foreign3, institution3  : 직전 3개월 합
DART 재무는 2015년 하반기부터라 학습 구간(2012 ~ 2015)을 덮지 못해 넣지 않는다.
"""
from research.data import load_panel
from research.examples.swing_event import load_high_low

PRICE = ['open', 'high', 'low', 'close', 'vwap', 'volume', 'amount', 'returns', 'mcap']
KRX = ['per', 'pbr', 'div', 'foreign', 'institution', 'foreign3', 'institution3']
FEATURES = PRICE + KRX


def features(p):
    first = p.close.bfill().iloc[0] / p.idx.bfill().iloc[0]   # 종목별 상수: 처음 나온 날 실제 종가 / 지수
    close = p.idx * first
    g = close / p.close                                      # 그날의 수정 계수 (분할 전 1)
    hi, lo = load_high_low(p)
    traded = p.volume > 0
    out = {
        'open': (p.open * g).where(p.open > 0),
        'high': (hi * g).where(traded),
        'low': (lo * g).where(traded),
        'close': close,
        'vwap': (p.amount / p.volume.where(traded)) * g,
        'volume': (p.volume / g).where(traded),
        'amount': p.amount,
        'returns': p.ret,
        'mcap': p.mcap,
    }
    if p.krx:
        out.update({k: p.krx[k].where(p.krx[k] > 0) if k in ('per', 'pbr') else p.krx[k] for k in KRX})
    return out


def load(start, end, krx=True):
    """(패널, 피처). 마이너는 end를 탐색 구간 끝(2019-12-31)까지만 준다"""
    p = load_panel(start, end)
    if krx:
        p.add_krx()
    return p, features(p)

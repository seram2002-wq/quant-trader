"""측정: IC가 얼마나 높아야 이 저장소의 롱온리 구조로 채택 기준을 넘나 — 2026-11-23

    python -m research.examples.required_ic

미래 수익률에 잡음을 섞어 순위 IC를 원하는 값으로 맞춘 가짜 신호를 만들고, 다른 후보와 똑같이 judge()에 넣는다.
미래 정보를 일부러 쓰는 측정이라 전략 후보가 아니다 (시험 횟수에 넣지 않음).

가짜 신호 (날마다 단면으로)
    u = 앞으로 h거래일 수익률의 순위를 표준화한 값  (엔진이 점수를 lag=2일 늦춰 쓰므로, 점수 날짜 t의 u는 t+2 ~ t+2+h 수익률)
    점수 = a * u + 잡음,  a = IC / sqrt(1 - IC^2),  잡음 ~ 표준정규 (시드 고정)
    → u와의 상관이 IC가 된다. 실제로 맞았는지 시가총액 상위 200 안의 순위 IC로 다시 잰다
    상장폐지 종목은 마지막 가격으로 계산해서, 가짜 신호가 상장폐지를 미리 피하지 못하게 한다

미리 고정
    IC 0.02, 0.03, 0.05, 0.08, 0.10 × 교체 10일(h=10)·21일(h=21). 나머지는 judge() 기본
    (탐색 2012 ~ 2019, 검증 2020 ~ 2024, 범위 150·200·300 × 20·30종목 중앙값, 업종 중립 없음, 비용 config)
    2025년 이후는 불러오지 않는다
"""
import numpy as np
import pandas as pd

from research.data import load_panel
from research.evaluate import SEARCH, VALID, judge

LEVELS = (0.02, 0.03, 0.05, 0.08, 0.10)
HORIZONS = (10, 21)
LAG = 2


def forward(p, h):
    """점수 날짜 t 기준 t+LAG ~ t+LAG+h 수익률. 상장폐지는 마지막 가격으로"""
    px = p.idx.ffill()
    return (px.shift(-(LAG + h)) / px.shift(-LAG) - 1).where(p.idx.notna())


def synthetic(p, fwd, ic, seed=0):
    ok = p.eligible & (p.amount20 >= 1e9) & fwd.notna()
    r = fwd.where(ok).rank(axis=1, pct=True)
    u = r.sub(r.mean(axis=1), axis=0).div(r.std(axis=1), axis=0)
    noise = np.random.default_rng(seed).standard_normal(u.shape)
    return (ic / np.sqrt(1 - ic ** 2) * u + noise).where(ok)


def realized_ic(p, score, fwd, a, b, size=200):
    """시가총액 상위 size 안에서 점수와 앞으로 수익률의 날별 순위 상관 평균"""
    ok = p.eligible & (p.amount20 >= 1e9)
    top = p.mcap.where(ok).rank(axis=1, ascending=False) <= size
    s, r = score.where(top).loc[a:b].rank(axis=1), fwd.where(top).loc[a:b].rank(axis=1)
    return s.corrwith(r, axis=1).mean()


if __name__ == '__main__':
    p = load_panel('2010-06-01', VALID[1])                         # 2025년 이후는 불러오지 않음
    rows = []
    for h in HORIZONS:
        fwd = forward(p, h)
        for ic in LEVELS:
            score = synthetic(p, fwd, ic)
            table, ok = judge(p, score, name=f'가짜 신호 IC {ic:.2f}, {h}일 교체', every=h)
            rows.append({'교체': f'{h}일', '목표 IC': ic,
                         '실제 IC (탐색, 상위 200)': round(realized_ic(p, score, fwd, *SEARCH), 4),
                         '탐색 (중앙값)': table.iloc[0]['전략 (중앙값)'], '검증 (중앙값)': table.iloc[1]['전략 (중앙값)'],
                         '판정': '통과' if ok else '탈락'})
    print('\n== 요약')
    print(pd.DataFrame(rows).to_string(index=False))

"""측정: 시장 하락 때 주식 비중을 줄이면 낙폭 조건을 넘나 — 2026-11-23

    python -m research.examples.drawdown_overlay

12절(required_ic.py)에서 10일 교체는 IC가 높아도 낙폭에서 막혔다. 같은 가짜 신호(IC를 맞춘 미래 수익률 + 잡음)로
백테스트한 자산 곡선에 시장 국면 장치를 덧씌워, 낙폭 조건을 넘는지와 그 대가(수익 감소)를 잰다.
미래 정보를 일부러 쓰는 측정이라 전략 후보가 아니다. 엔진은 고치지 않고 결과 곡선에 덧씌운다.

국면 장치 (미리 고정)
    코스피(직접 계산)가 120일 이동평균 아래인 날 다음 날부터 주식 비중 w, 위로 올라오면 다시 100%
    w = 100% (장치 없음) / 50% / 0% (전부 현금, 이자 0)
    비중을 바꿀 때 바뀐 만큼 비용: 줄일 때 수수료 + 슬리피지 + 매도세, 늘릴 때 수수료 + 슬리피지
    근사: 현금 구간에도 엔진의 종목 교체 비용은 비중만큼 그대로 반영된다

조합 (미리 고정): 상위 200 안 실제 IC 약 0.025 / 0.04 / 0.066 (목표 0.03 / 0.05 / 0.08) × 교체 21일 / 10일 × w 3가지
판정: judge()와 같은 기준 (탐색 2012 ~ 2019, 검증 2020 ~ 2024, 범위 150·200·300 × 20·30종목 중앙값). 2025년 이후는 불러오지 않는다
"""
import numpy as np
import pandas as pd

import config
from research.data import load_panel
from research.engine import backtest, stats_of
from research.evaluate import GRID, SEARCH, VALID, passes
from research.examples.required_ic import forward, synthetic

LEVELS = (0.03, 0.05, 0.08)
HORIZONS = (21, 10)
WEIGHTS = (1.0, 0.5, 0.0)
MA = 120
SELL = config.FEE_RATE + config.SLIPPAGE + config.STOCK_SELL_TAX
BUY = config.FEE_RATE + config.SLIPPAGE


def overlay(equity, down, w):
    """자산 곡선에 국면 장치를 덧씌운 곡선. down: 그날 종가 기준 하락 국면(bool, 같은 날짜)"""
    r = equity.pct_change().fillna(0.0)
    weight = pd.Series(np.where(down, w, 1.0), index=equity.index).shift(1).fillna(1.0)
    dw = weight.diff().fillna(0.0)
    cost = np.where(dw < 0, -dw * SELL, dw * BUY)
    return (1 + weight * r - cost).cumprod() * equity.iloc[0]


def self_check():
    eq = pd.Series([100.0, 110, 99, 99, 108.9])               # +10%, -10%, 0%, +10%
    down = pd.Series([False, True, True, False, False])
    out = overlay(eq, down, 0.0)
    # 1일째 신호(하락) → 2일째부터 현금: 2일째 -10% 피함, 3일째 0%, 4일째 다시 100%
    expected = 100 * 1.10 * (1 - SELL) * 1.0 * (1 + 0.10 - BUY)    # 다시 사는 날 비용은 그날 수익에서 뺌
    assert abs(out.iloc[-1] - expected) < 1e-9, (out.iloc[-1], expected)
    assert (overlay(eq, down, 1.0) - eq).abs().max() < 1e-9   # 장치 없음 = 그대로


if __name__ == '__main__':
    self_check()
    p = load_panel('2010-06-01', VALID[1])                    # 2025년 이후는 불러오지 않음
    down_all = p.kospi < p.kospi.rolling(MA, min_periods=MA).mean()
    rows = []
    for h in HORIZONS:
        fwd = forward(p, h)
        for ic in LEVELS:
            score = synthetic(p, fwd, ic)
            curves = {(label, cfg): backtest(p, score, a, b, size=cfg[0], n=cfg[1], every=h).equity
                      for label, (a, b) in (('탐색', SEARCH), ('검증', VALID)) for cfg in GRID}
            for w in WEIGHTS:
                row, ok_all = {'교체': f'{h}일', '목표 IC': ic, '하락 국면 비중': f'{w:.0%}'}, True
                for label, (a, b), extra in (('탐색', SEARCH, 0.0), ('검증', VALID, 0.05)):
                    res = [stats_of(overlay(curves[label, cfg], down_all.reindex(curves[label, cfg].index), w))
                           for cfg in GRID]
                    med = {k: float(np.median([r[k] for r in res])) for k in ('cagr', 'mdd')}
                    k = stats_of(p.kospi.loc[a:b])
                    ok = passes(med, k, extra)
                    ok_all &= ok
                    row[label] = f"{med['cagr']:+.1%}, {med['mdd']:.0%}" + ('' if ok else ' ✗')
                row['판정'] = '통과' if ok_all else '탈락'
                rows.append(row)
            print(pd.DataFrame(rows[-len(WEIGHTS):]).to_string(index=False), flush=True)
    k_s, k_v = stats_of(p.kospi.loc[SEARCH[0]:SEARCH[1]]), stats_of(p.kospi.loc[VALID[0]:VALID[1]])
    print(f"\n== 요약 (코스피 탐색 {k_s['cagr']:+.1%}, {k_s['mdd']:.0%} / 검증 {k_v['cagr']:+.1%}, {k_v['mdd']:.0%}."
          f" 통과선: 탐색 코스피 이상, 검증 코스피 + 5%p 이상, 둘 다 낙폭 더 작게. ✗ = 그 구간 미달)")
    print(pd.DataFrame(rows).to_string(index=False))
    print(f"\n하락 국면 날 비율: 탐색 {down_all.loc[SEARCH[0]:SEARCH[1]].mean():.0%}, 검증 {down_all.loc[VALID[0]:VALID[1]].mean():.0%}")

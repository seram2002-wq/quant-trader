"""측정: 중형주(시가총액 201 ~ 1000위)에서는 IC가 얼마나 필요하고, 가격-거래량 계열 IC는 얼마인가 — 2026-11-23

    python -m research.examples.midcap_measure

1부 필요한 IC (12·13절과 같은 가짜 신호, 미래 정보를 일부러 쓰는 측정이라 후보 아님)
    엔진은 그대로 두고 상위 200 종목의 점수를 비워서(NaN) 엔진이 201위부터 800종목 안에서 고르게 한다
    20·30종목, 10거래일마다 교체. 하락 국면 장치 없음 / 코스피 120일선 아래면 비중 50%
    슬리피지 한쪽 0.05% (기본) / 0.15% (중형주 호가 차이를 크게 잡은 경우)
    판정은 judge()와 같은 기준 (탐색 2012 ~ 2019 코스피 이상, 검증 2020 ~ 2024 코스피 + 5%p 이상, 낙폭 더 작게)
2부 가격-거래량 계열 실제 IC (마이너 15절에서 가장 가까웠던 4개, 탐색 구간만)
    부호는 장부대로 (상위 200, 학습 구간으로 정한 것). 상위 200과 중형주에서 10일 IC를 나란히
2025년 이후는 불러오지 않는다
"""
import numpy as np
import pandas as pd

import config
from alpha_miner.data.loader import features
from alpha_miner.engine.ast_parser import AlphaASTParser
from alpha_miner.evaluation.metrics import ic_series
from research.data import load_panel
from research.engine import backtest, stats_of
from research.evaluate import SEARCH, VALID, passes
from research.examples.drawdown_overlay import MA, overlay
from research.examples.required_ic import forward, synthetic

LEVELS = (0.03, 0.05, 0.08)
SLIPS = (0.0005, 0.0015)
NS = (20, 30)
H = 10
HALVES = {'A': ('2012-01-01', '2015-12-31'), 'B': ('2016-01-01', '2019-12-31')}
FAMILY = [
    'ts_corr(close, volume, 30)',
    'cs_rank(ts_mean(ts_corr(close, volume/ts_mean(volume,20), 30), 5) / (1 + ts_std(returns, 5)))',
    'cs_rank(-ts_corr(returns, ts_mean(volume,20)/mcap, 30))',
    'cs_rank(ts_corr(close, amount/mcap, 30) / (1 + ts_std(returns, 10)))',
]


def ranks(p):
    ok = p.eligible & (p.amount20 >= 1e9)
    return p.mcap.where(ok).rank(axis=1, ascending=False, method='first')


if __name__ == '__main__':
    p = load_panel('2010-06-01', VALID[1])                    # 2025년 이후는 불러오지 않음
    rk = ranks(p)
    top, mid = rk <= 200, (rk > 200) & (rk <= 1000)
    down = p.kospi < p.kospi.rolling(MA, min_periods=MA).mean()
    fwd = forward(p, H)
    base_slip = config.SLIPPAGE

    print('== 1부: 중형주에서 필요한 IC')
    rows = []
    for ic in LEVELS:
        score = synthetic(p, fwd, ic)
        real_ic = ic_series(score.loc[SEARCH[0]:SEARCH[1]], fwd.loc[SEARCH[0]:SEARCH[1]], mid.loc[SEARCH[0]:SEARCH[1]]).mean()
        score_mid = score.where(~top)                         # 상위 200은 비워서 201위부터
        for slip in SLIPS:
            config.SLIPPAGE = slip
            for w in (1.0, 0.5):
                row, ok_all = {'목표 IC': ic, '중형주 실제 IC': round(real_ic, 4), '슬리피지': f'{slip:.2%}',
                               '하락 국면 비중': f'{w:.0%}'}, True
                for label, (a, b), extra in (('탐색', SEARCH, 0.0), ('검증', VALID, 0.05)):
                    res = []
                    for n in NS:
                        eq = backtest(p, score_mid, a, b, size=800, n=n, every=H).equity
                        res.append(stats_of(overlay(eq, down.reindex(eq.index), w)))
                    med = {k: float(np.median([r[k] for r in res])) for k in ('cagr', 'mdd')}
                    ok = passes(med, stats_of(p.kospi.loc[a:b]), extra)
                    ok_all &= ok
                    row[label] = f"{med['cagr']:+.1%}, {med['mdd']:.0%}" + ('' if ok else ' ✗')
                row['판정'] = '통과' if ok_all else '탈락'
                rows.append(row)
                print(row, flush=True)
    config.SLIPPAGE = base_slip
    print(pd.DataFrame(rows).to_string(index=False))

    print('\n== 2부: 가격-거래량 계열 10일 IC (탐색 구간만, 부호는 상위 200 학습 구간 기준)')
    parser = AlphaASTParser(features(p))
    rows = []
    for expr in FAMILY:
        s = parser.evaluate(expr).reindex(p.dates)
        a, b = HALVES['A']
        sign = 1.0 if ic_series(s.loc[a:b], fwd.loc[a:b], top.loc[a:b]).mean() >= 0 else -1.0
        row = {'수식': expr[:70]}
        for uname, m in (('상위200', top), ('중형주', mid)):
            for k, (a, b) in HALVES.items():
                row[f'{uname} {k}'] = round(sign * ic_series(s.loc[a:b], fwd.loc[a:b], m.loc[a:b]).mean(), 4)
        rows.append(row)
    print(pd.DataFrame(rows).to_string(index=False))
    k_s, k_v = stats_of(p.kospi.loc[SEARCH[0]:SEARCH[1]]), stats_of(p.kospi.loc[VALID[0]:VALID[1]])
    print(f"\n코스피 탐색 {k_s['cagr']:+.1%}, {k_s['mdd']:.0%} / 검증 {k_v['cagr']:+.1%}, {k_v['mdd']:.0%}")

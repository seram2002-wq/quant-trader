"""가격-거래량 상관 2개 + 중형주 구조 백테스트 (탐색 구간만) — 2026-11-23

    python -m research.examples.midcap_pv

16절에서 중형주 IC가 문턱(0.04 ~ 0.05)에 닿은 단순한 수식 2개. 아래는 결과를 보기 전에 고정.
    수식   : ts_corr(close, volume, 30)
             cs_rank(ts_corr(close, amount/mcap, 30) / (1 + ts_std(returns, 10)))
             부호는 + (마이너 장부, 상위 200 학습 구간으로 정한 그대로)
    구조   : 중형주(시가총액 201 ~ 1000위, 상위 200 점수를 비워 엔진이 800종목 안에서 고름), 20·30종목 중앙값,
             10거래일마다 교체, 코스피가 120일선 아래면 주식 비중 50%
    판정   : 학습 2012 ~ 2015, 선택 2016 ~ 2019 모두 같은 기간 코스피보다 연 수익 높고 낙폭 작게 (마이너와 같은 기준)
    슬리피지: 한쪽 0.05% (기본) / 0.15% (중형주 호가 차이를 크게 잡은 경우). 판정은 0.05% 기준, 0.15%는 참고
    2020년 이후는 불러오지 않는다. 둘 다 통과하면 검증 구간(2020 ~ 2024)은 따로 한 번만
시험 횟수: 후보 2개 × 1회
"""
import numpy as np
import pandas as pd

import config
from alpha_miner.data.loader import features
from alpha_miner.engine.ast_parser import AlphaASTParser
from research.data import load_panel
from research.engine import backtest, stats_of
from research.examples.drawdown_overlay import MA, overlay
from research.examples.midcap_measure import ranks

FORMULAS = ['ts_corr(close, volume, 30)',
            'cs_rank(ts_corr(close, amount/mcap, 30) / (1 + ts_std(returns, 10)))']
HALVES = {'학습 2012 ~ 2015': ('2012-01-01', '2015-12-31'), '선택 2016 ~ 2019': ('2016-01-01', '2019-12-31')}
SLIPS = (0.0005, 0.0015)
NS = (20, 30)

if __name__ == '__main__':
    p = load_panel('2010-06-01', '2019-12-31')                # 2020년 이후는 불러오지 않음
    top = ranks(p) <= 200
    down = p.kospi < p.kospi.rolling(MA, min_periods=MA).mean()
    parser = AlphaASTParser(features(p))
    base = config.SLIPPAGE
    rows = []
    for expr in FORMULAS:
        score = parser.evaluate(expr).reindex(p.dates).where(~top)
        for slip in SLIPS:
            config.SLIPPAGE = slip
            row, ok_all = {'수식': expr, '슬리피지': f'{slip:.2%}'}, True
            for label, (a, b) in HALVES.items():
                res = []
                for n in NS:
                    eq = backtest(p, score, a, b, size=800, n=n, every=10).equity
                    res.append(stats_of(overlay(eq, down.reindex(eq.index), 0.5)))
                med = {k: float(np.median([r[k] for r in res])) for k in ('cagr', 'mdd')}
                k = stats_of(p.kospi.loc[a:b])
                ok = med['cagr'] >= k['cagr'] and med['mdd'] > k['mdd']
                ok_all &= ok
                row[label] = (f"{med['cagr']:+.1%}, {med['mdd']:.0%} (코스피 {k['cagr']:+.1%}, {k['mdd']:.0%})"
                              + ('' if ok else ' ✗'))
            row['판정'] = '통과' if ok_all else '탈락'
            rows.append(row)
            print(row, flush=True)
    config.SLIPPAGE = base
    print('\n== 요약 (판정은 슬리피지 0.05% 줄 기준. ✗ = 그 구간 미달)')
    print(pd.DataFrame(rows).to_string(index=False))

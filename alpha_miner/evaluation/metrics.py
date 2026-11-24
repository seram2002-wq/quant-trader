"""순위 IC, ICIR, 회전율

시점 맞추기는 research 엔진과 같다: 점수는 lag=2일 늦게 쓰고 (자료가 늦게 오는 실제 상황),
점수 날짜 t의 h일 수익률 = t+2 ~ t+2+h (research.examples.required_ic.forward).
평가 종목 = 그날 시가총액 상위 size (보통주, 20일 평균 거래대금 10억 이상). 12·13절 문턱도 상위 200 기준.
"""
import numpy as np
import pandas as pd

from research.examples.required_ic import forward


def universe(p, size=200):
    ok = p.eligible & (p.amount20 >= 1e9)
    return p.mcap.where(ok).rank(axis=1, ascending=False, method='first') <= size


def ic_series(score, fwd, mask):
    """날마다 단면 순위 상관(score, fwd). 종목 20개 미만인 날은 뺌"""
    s, r = score.where(mask), fwd.where(mask)
    both = s.notna() & r.notna()
    ic = s.where(both).rank(axis=1).corrwith(r.where(both).rank(axis=1), axis=1)
    return ic[both.sum(axis=1) >= 20]


def turnover(score, mask, n=20):
    """점수 상위 n종목을 매일 새로 고를 때 하루에 바뀌는 비율 (0 ~ 1)"""
    top = score.where(mask).rank(axis=1, ascending=False, method='first') <= n
    kept = (top & top.shift(1, fill_value=False)).sum(axis=1)
    held = top.sum(axis=1)
    return (1 - kept / held.where(held > 0)).iloc[1:].mean()


def top_excess(score, fwd, mask, n=20, every=10, min_names=100, cost=None, bench=None):
    """every일마다 점수 상위 n종목을 새로 고를 때, 교체 1번당 (상위 n 평균 수익 - 기준 수익 - 바뀐 비율 x 왕복 비용).
    기준 = bench(날짜별 같은 기간 수익, 예: 코스피)가 있으면 그것, 없으면 평가 종목 평균.
    17절: IC가 플러스여도 맨 위가 가장 나쁠 수 있어서, 롱온리는 실제로 사는 맨 위만 본다.
    점수가 있는 평가 종목이 min_names개 미만인 날은 뺀다. 첫 교체는 전부 새로 산 것으로 센다"""
    import config
    cost = 2 * (config.FEE_RATE + config.SLIPPAGE) + config.STOCK_SELL_TAX if cost is None else cost
    s = score.where(mask)
    s = s[s.notna().sum(axis=1) >= min_names].iloc[::every]
    m, r = mask.reindex(index=s.index, columns=s.columns), fwd.reindex(index=s.index, columns=s.columns)
    top = s.rank(axis=1, ascending=False, method='first') <= n
    base = r.where(m).mean(axis=1) if bench is None else bench.reindex(s.index)
    gross = r.where(top).mean(axis=1) - base
    changed = 1 - (top & top.shift(1, fill_value=False)).sum(axis=1) / n
    return gross - changed * cost


def summary(p, score, horizons=(1, 10), size=200, n=20):
    """{IC_h, ICIR_h, 회전율, 평가일 수}"""
    mask = universe(p, size)
    out = {}
    for h in horizons:
        ic = ic_series(score, forward(p, h), mask)
        out[f'IC {h}일'] = ic.mean()
        out[f'ICIR {h}일'] = ic.mean() / ic.std() if ic.std() > 0 else np.nan
        out['평가일'] = len(ic)
    out[f'상위 {n} 하루 회전율'] = turnover(score, mask, n)
    return out


def table(rows):
    return pd.DataFrame(rows).round(4)

"""종목 선택 전략 백테스트 엔진

점수표(날짜 × 종목, 높을수록 좋음)를 주면, 정해진 날마다 점수 상위 종목을 같은 금액으로 사고
순위가 밀린 종목을 판다. 수수료·매도 세금·슬리피지, 상장폐지, 거래정지를 반영한다.

    from research.engine import backtest
    res = backtest(p, score, '2016-01-01', '2019-12-31', n=20)
    print(res.summary())

미래 정보 방지
    - 점수표는 lag 거래일 늦춰서 쓴다 (기본 2일). 데이터가 늦게 오는 실제 상황과 같게
    - 매매는 그날 종가로 (실시간 전략의 15:05 매매와 비슷)
    - 정답(이후 수익)을 점수에 쓰지 않도록 주의. 점수는 그날까지의 값으로만 만든다
"""
from collections import Counter
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

import config

TRADING_DAYS = 252


def rank01(x):
    """값이 클수록 1에 가까운 순위 (0 ~ 1)"""
    order = x.argsort().argsort()
    return order / (len(x) - 1) if len(x) > 1 else np.ones(len(x))


def rank_in_groups(x, groups):
    """그룹(업종) 안에서의 순위. 그룹을 모르거나 3종목 미만이면 전체 순위"""
    out = np.full(len(x), np.nan)
    for g in np.unique(groups):
        m = groups == g
        if g >= 0 and m.sum() >= 3:
            out[m] = rank01(x[m])
    rest = np.isnan(out)
    if rest.any():
        out[rest] = rank01(x)[rest]
    return out


@dataclass
class Result:
    equity: pd.Series                       # 날짜별 자산
    trades: pd.DataFrame                    # 매매 내역
    kospi: pd.Series                        # 같은 기간 코스피(직접 계산) 지수
    turnover: float = 0.0                   # 연 회전율 (매도 금액 ÷ 평균 자산)
    stats: dict = field(default_factory=dict)

    def summary(self):
        s, k = self.stats, stats_of(self.kospi)
        return (f"연 {s['cagr']:+.1%}, 낙폭 {s['mdd']:.0%}, 샤프 {s['sharpe']:.2f}, "
                f"거래 {len(self.trades)}건, 회전율 연 {self.turnover:.1f}배 "
                f"(코스피 연 {k['cagr']:+.1%}, 낙폭 {k['mdd']:.0%})")


def stats_of(series):
    r = series.pct_change().dropna()
    if len(r) < 2:
        return {'cagr': 0.0, 'vol': 0.0, 'sharpe': 0.0, 'mdd': 0.0}
    years = len(r) / TRADING_DAYS
    cagr = (series.iloc[-1] / series.iloc[0]) ** (1 / years) - 1
    vol = r.std() * np.sqrt(TRADING_DAYS)
    return {'cagr': cagr, 'vol': vol, 'sharpe': r.mean() * TRADING_DAYS / vol if vol > 0 else 0.0,
            'mdd': (series / series.cummax() - 1).min()}


def backtest(p, score, start, end, n=20, hold=None, size=200, min_value=1e9, every=21,
             lag=2, neutral=False, sector_cap=None, capital=10_000_000, sell_tax=None):
    """
    p          : research.data.Panel
    score      : 날짜 × 종목 점수표 (DataFrame). NaN인 종목은 사지 않음 (보유 중이면 판다)
    n          : 보유 종목 수
    hold       : 보유 종목은 이 순위 안이면 계속 보유 (기본 2n, 매매를 줄이려고)
    size       : 종목 범위 = 시가총액 상위 몇 개 (보통주, 거래대금 min_value 이상)
    every      : 며칠마다 교체할지 (21 = 월 1회, 5 = 주 1회, 1 = 매일)
    lag        : 점수를 몇 거래일 늦춰 쓸지
    neutral    : True면 업종 안 순위로 고름
    sector_cap : 같은 업종 최대 종목 수 (None이면 제한 없음)
    sell_tax   : 매도 세금 (기본 config.STOCK_SELL_TAX)
    """
    hold = hold or 2 * n
    fee, slip = config.FEE_RATE, config.SLIPPAGE
    tax = config.STOCK_SELL_TAX if sell_tax is None else sell_tax
    dates, codes = p.dates, np.array(p.codes)
    S = score.reindex(index=dates, columns=p.codes).shift(lag).to_numpy(dtype='float64')
    IDX = p.idx.to_numpy()
    IDXF = p.idx.ffill().to_numpy()
    MC = p.mcap.shift(lag).to_numpy()
    AMT = p.amount20.shift(lag).to_numpy()
    ELIG = p.eligible.to_numpy()
    VOL = p.volume.to_numpy()
    SEC_ID = {s: i for i, s in enumerate(sorted(set(p.sector.values())))}
    SEC = np.array([SEC_ID.get(p.sector.get(c, ''), -1) for c in p.codes])
    days = np.where((dates >= start) & (dates <= end))[0]

    cash, pos, curve, trades, sold = float(capital), {}, [], [], 0.0
    buy_info = {}

    def sell(c, px, t, why):
        nonlocal cash, sold
        units = pos.pop(c)
        gross = units * px * (1 - slip)
        cash += gross * (1 - fee - tax)
        sold += gross
        bt, bp = buy_info.pop(c)
        trades.append({'code': codes[c], 'name': p.names.get(codes[c], ''), 'buy': dates[bt],
                       'sell': dates[t], 'return': px / bp - 1, 'why': why})

    for i, t in enumerate(days):
        px = IDX[t]
        for c in list(pos):                                   # 상장폐지·자료 없음
            if np.isnan(px[c]):
                sell(c, IDXF[t][c], t, '상장폐지')
        if i % every == 0:
            ok = ELIG[t] & (AMT[t] >= min_value) & ~np.isnan(px) & ~np.isnan(MC[t]) & ~np.isnan(S[t])
            cand = np.where(ok)[0]
            top = cand[np.argsort(-MC[t][cand])][:size]
            pool = np.array(sorted(set(top) | {c for c in pos if ok[c]}), dtype=int)
            ranked = []
            if len(pool):
                sc = rank_in_groups(S[t][pool], SEC[pool]) if neutral else S[t][pool]
                ranked = pool[np.argsort(-sc, kind='stable')]
            rank = {c: j + 1 for j, c in enumerate(ranked)}
            per_sector = Counter()

            def room(c):
                return sector_cap is None or SEC[c] < 0 or per_sector[SEC[c]] < sector_cap
            keep = []
            for c in sorted(pos, key=lambda c: rank.get(c, 10 ** 9)):
                if rank.get(c, 10 ** 9) <= hold and len(keep) < n and room(c):
                    keep.append(c)
                    per_sector[SEC[c]] += 1
            for c in ranked:
                if len(keep) >= n or rank[c] > (hold if sector_cap else n):
                    break
                if c not in keep and room(c):
                    keep.append(c)
                    per_sector[SEC[c]] += 1
            keep_set = set(keep)
            for c in list(pos):
                if c not in keep_set and VOL[t][c] > 0:
                    sell(c, px[c], t, '순위 밖' if ok[c] else '조건 탈락')
            equity = cash + sum(u * px[c] for c, u in pos.items())
            for c in keep:
                if c in pos or VOL[t][c] <= 0 or len(pos) >= n:
                    continue
                amount = min(equity * 0.95 / n, cash / (1 + fee))
                if amount < equity * 0.95 / n * 0.5:
                    continue
                pos[c] = amount / (px[c] * (1 + slip))
                cash -= amount * (1 + fee)
                buy_info[c] = (t, px[c])
        curve.append(cash + sum(u * px[c] for c, u in pos.items()))
    eq = pd.Series(curve, index=dates[days])
    years = max(len(eq) / TRADING_DAYS, 1e-9)
    res = Result(eq, pd.DataFrame(trades), p.kospi.loc[eq.index[0]:eq.index[-1]],
                 turnover=sold / eq.mean() / years)
    res.stats = stats_of(eq)
    return res


def equal_weight(p, start, end, size=200, **kw):
    """비교 기준: 시가총액 상위 size개를 같은 금액으로 (월 1회)"""
    rnd = pd.DataFrame(np.random.RandomState(0).rand(len(p.dates), len(p.codes)),
                       index=p.dates, columns=p.codes)
    return backtest(p, rnd, start, end, n=size, hold=size, size=size, **kw)

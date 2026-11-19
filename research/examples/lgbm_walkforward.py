"""LightGBM 종목 선택 (굴려 가며 학습) — pip install lightgbm 필요

    python -m research.examples.lgbm_walkforward

정답: 21거래일 뒤 수익률의 업종 평균 대비 초과분 (날짜별 순위)
학습: 해마다 1월에 그 전까지의 자료로 다시 학습. 정답 기간이 시험 시작 전에 끝나도록 간격을 둔다
특징: 가격 10개 (+ DART 재무 5개, + 거래소 수급·배당) — 날짜별 순위와 업종 안 순위
2026-11-19 결과: 예측 IC +0.043 (t 4.2)까지 나왔지만 상위 20 ~ 30종목 롱온리 수익은 기준 미달
"""
import numpy as np
import pandas as pd

from research.data import load_panel
from research.evaluate import judge
from research import factors as f

LAG = 2
PARAMS = dict(objective='regression', learning_rate=0.05, num_leaves=15, min_child_samples=200,
              subsample=0.8, subsample_freq=1, colsample_bytree=0.8, n_estimators=300, verbose=-1)


def features(p, use_dart=False, use_krx=False):
    x = {'mom12': f.momentum(p, 12, 1), 'mom6': f.momentum(p, 6, 1), 'rev21': f.reversal(p, 21),
         'rev5': f.reversal(p, 5), 'lowvol60': f.low_volatility(p, 60), 'lowvol250': f.low_volatility(p, 250),
         'high52': f.high52(p), 'turn': f.low_turnover(p), 'size': f.small(p),
         'lowmax': -p.ret.rolling(21, min_periods=15).max()}
    if use_dart:
        x.update({'bp': f.book_to_price(p), 'ep': f.earnings_yield(p), 'roe': f.roe(p),
                  'opa': f.operating_profitability(p), 'lowlev': f.low_leverage(p)})
    if use_krx:
        x.update({'inst3': f.institution_selling(p, 3), 'frgn3': f.foreign_selling(p, 3),
                  'div': f.dividend_yield(p)})
    return {k: v.shift(LAG) for k, v in x.items()}          # 실제로 쓸 수 있는 날로 늦춤


def universe(p, t, size=200):
    ok = p.eligible.iloc[t] & (p.amount20.shift(LAG).iloc[t] >= 1e9) & p.idx.iloc[t].notna()
    mc = p.mcap.shift(LAG).iloc[t][ok].dropna()
    return mc.sort_values(ascending=False).index[:size]


def rows_at(p, X, t, codes, fwd=None):
    sec = pd.Series([p.sector.get(c, '?') for c in codes], index=codes)
    d = {}
    for k, v in X.items():
        s = v.iloc[t].reindex(codes)
        d[k] = s.rank(pct=True)
        d[k + '_sec'] = s.groupby(sec).rank(pct=True)
    df = pd.DataFrame(d)
    if fwd is not None:
        y = fwd.iloc[t].reindex(codes)
        df['y'] = (y - y.groupby(sec).transform('mean')).rank(pct=True)
    return df


def walk_forward(p, X, first_train, test_years):
    import lightgbm as lgb
    fwd = p.idx.ffill().shift(-21) / p.idx - 1
    sample = [t for t in range(len(p.dates)) if p.dates[t] >= pd.Timestamp(first_train)][::5]
    data = pd.concat([rows_at(p, X, t, universe(p, t), fwd).assign(t=t) for t in sample
                      if t + 21 < len(p.dates)])
    pred = pd.DataFrame(np.nan, index=p.dates, columns=p.codes)
    for y in test_years:
        start = int(np.searchsorted(p.dates, pd.Timestamp(f'{y}-01-01')))
        train = data[(data['t'] <= start - 21 - LAG - 1) & data['y'].notna()]
        cols = [c for c in train.columns if c not in ('y', 't')]
        m = lgb.LGBMRegressor(random_state=0, **PARAMS).fit(train[cols], train['y'])
        for t in np.where(p.dates.year == y)[0]:
            codes = universe(p, t)
            if len(codes):
                pred.iloc[t, pred.columns.get_indexer(codes)] = m.predict(rows_at(p, X, t, codes)[cols])
        print(f'{y} 예측 완료', flush=True)
    return pred                        # 특징을 이미 늦췄으므로 backtest()에는 lag=0으로 넘긴다


if __name__ == '__main__':
    p = load_panel('2010-06-01')
    X = features(p)
    pred = walk_forward(p, X, '2011-06-01', range(2013, 2025))
    judge(p, pred, name='LightGBM (가격만)', search=('2013-01-01', '2019-12-31'), lag=0)

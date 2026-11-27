"""밤사이 보유(KODEX 200) 크기 조절: ① 최근 밤사이 변동성에 맞춰 줄이기 ③ VIX 높으면 쉬기 — 2026-11-27

    python -m research.examples.overnight_risk_sizing

방향은 못 맞히므로(3-6절, R² ≈ 0) 위험이 클 때 덜 거는 것만 본다.
자료: data/research/intraday/069500_1d.csv (야후 일봉, 분배금은 Adj Close 비율로 반영), VIX는 야후 ^VIX
밤사이 수익 = 오늘 시가 ÷ 어제 종가 - 1 (분배금 반영). 비중 w는 어제 장 마감 때 알던 값으로만 정한다
    ① 변동성: w = min(1, 목표 ÷ 최근 20일 밤사이 변동성). 목표 = 탐색 구간(2012 ~ 2019)의 밤사이 변동성 (검증 구간을 보지 않음)
    ③ VIX   : 어제 장 마감 때 알던 VIX(미국 전날 종가)가 30 이상이면 w = 0.   참고만: 25 이상이면 0.5
    ①+③     : 둘을 곱한 것
비용: 그날 비중만큼 왕복 0.03% (가상 장부 조건). 2025년 이후는 쓰지 않음 (봉인)
판정 (실행 전 확정): 같은 비용의 매일 전부 보유보다 ① 최대 낙폭이 작고 ② 샤프가 높음 — 탐색·검증 두 구간 모두면 '개선'
"""
import numpy as np
import pandas as pd
import yfinance as yf

from research.data import RESEARCH

PERIODS = {'탐색': ('2012-01-01', '2019-12-31'), '검증': ('2020-01-01', '2024-12-31')}
COST, LOOKBACK, VIX_OFF = 0.0003, 20, 30


def overnight():
    d = pd.read_csv(RESEARCH / 'intraday' / '069500_1d.csv', index_col=0, parse_dates=True)
    d = d[(d['Open'] > 0) & (d['Volume'] > 0)]
    f = d['Adj Close'] / d['Close']                                   # 분배금 반영 비율
    return (d['Open'] * f / d['Adj Close'].shift(1) - 1).dropna()


def vix_known(index):
    """한국 날짜마다 그날 장 마감 때 알던 VIX (그 전 미국 거래일 종가)"""
    v = yf.download('^VIX', start='2011-01-01', end='2025-01-01', progress=False, auto_adjust=False)['Close']
    v = v.squeeze().dropna()
    v.index = v.index + pd.Timedelta(days=1)                          # 미국 날짜 d의 종가는 한국 날짜 d+1 아침에 앎
    return v.reindex(index, method='ffill')


def stats(r):
    eq = (1 + r).cumprod()
    cagr = eq.iloc[-1] ** (252 / len(r)) - 1
    return cagr, (eq / eq.cummax() - 1).min(), r.mean() / r.std() * np.sqrt(252) if r.std() > 0 else 0.0


def main():
    on = overnight()
    vol = on.rolling(LOOKBACK).std().shift(1)                         # 어제까지 20일 (오늘 밤 결과는 모름)
    target = on.loc[slice(*PERIODS['탐색'])].std()
    vix = vix_known(on.index).shift(1)                                # 어제 장 마감 때 = 그 전날 미국 종가
    w = {'매일 전부': pd.Series(1.0, index=on.index),
         '① 변동성': np.minimum(1, target / vol),
         '③ VIX ≥ 30 쉼': (vix < VIX_OFF).astype(float),
         '①+③': np.minimum(1, target / vol) * (vix < VIX_OFF),
         '참고: VIX ≥ 25 절반': np.where(vix >= 25, 0.5, 1.0)}
    rows = []
    for name, wt in w.items():
        wt = pd.Series(wt, index=on.index).fillna(1.0)
        r = wt * on - wt * COST
        for label, (a, b) in PERIODS.items():
            x, ww = r.loc[a:b], wt.loc[a:b]
            cagr, mdd, sh = stats(x)
            rows.append({'방법': name, '구간': label, '연 수익': cagr, '최대 낙폭': mdd, '샤프': sh, '평균 비중': ww.mean()})
    t = pd.DataFrame(rows)
    pd.set_option('display.width', 200)
    print(t.round(3).to_string(index=False))
    base = t[t['방법'] == '매일 전부'].set_index('구간')
    print('\n판정 (두 구간 모두 낙폭 작고 샤프 높으면 개선)')
    for name in ['① 변동성', '③ VIX ≥ 30 쉼', '①+③']:
        s = t[t['방법'] == name].set_index('구간')
        ok = all(s.loc[p, '최대 낙폭'] > base.loc[p, '최대 낙폭'] and s.loc[p, '샤프'] > base.loc[p, '샤프'] for p in PERIODS)
        print(f'  {name}: {"개선" if ok else "개선 아님"}')
    t.to_csv(RESEARCH / 'overnight_risk_sizing.csv', index=False, encoding='utf-8')


if __name__ == '__main__':
    main()

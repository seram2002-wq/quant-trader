"""밤사이 보유(KODEX 200) 아침 매도 시각: 전날 밤 SOXX·S&P가 빠진 날 언제 팔면 손실이 가장 작은가 — 2026-11-27

    python -m research.examples.overnight_exit_timing

봉인 해제: 장중 1분봉이 2025-12 이후에만 있어 2025년 이후 봉인 구간을 쓴다 (사용자 승인 11-27). 결과는 경향으로만 보고,
고른 규칙은 앞으로의 실전 기록으로 다시 확인해야 한다.
자료
    KODEX 200 1분봉 09:00 ~ 10:59: data/minute_hist/<날짜>/069500_105900.csv (장 마감 반전 백테스트 때 받은 것)
        + 11/19 이후는 data/minute/<날짜>/069500.csv
    전날 종가: data/research/intraday/069500_1d.csv (야후, 분배금은 Adj Close 비율로 반영)
    밤사이 미국: 야후 SOXX, ^GSPC, ^IXIC, ^VIX (한국 날짜 d 아침 = 그 전 미국 거래일 밤)
수익 = 매도가 ÷ 전날 종가 - 1 (밤사이 보유는 15:18에 사서 전날 종가와 거의 같음, 비용 전)
매도 시각: 09:00(첫 거래 봉 시가), 09:01·05·10·15·30, 10:00, 10:30, 10:59 종가. 참고: 09:00 ~ 10:59 최고가(사후에만 앎)
나눔: SOXX 밤사이 등락 구간, 시장 국면(전날 종가가 120일 평균 위/아래), 나스닥·VIX로 다시
"""
import numpy as np
import pandas as pd
import yfinance as yf

from research.data import RESEARCH

ROOT = RESEARCH.parent.parent
TIMES = ['0900', '0901', '0905', '0910', '0915', '0930', '1000', '1030', '1059']


def morning(day):
    for p in (ROOT / 'data' / 'minute_hist' / day / '069500_105900.csv', ROOT / 'data' / 'minute' / day / '069500.csv'):
        if p.exists():
            b = pd.read_csv(p, dtype={'time': str})
            b = b[(b['volume'] > 0) & (b['time'].str.zfill(6).str[:4] <= '1059')]
            if len(b):
                b['hhmm'] = b['time'].str.zfill(6).str[:4]
                return b.set_index('hhmm')
    return None


def main():
    d = pd.read_csv(RESEARCH / 'intraday' / '069500_1d.csv', index_col=0, parse_dates=True)
    d = d[(d['Open'] > 0) & (d['Volume'] > 0)]
    adj = d['Adj Close']
    ma120 = adj.rolling(120).mean()
    us = yf.download(['SOXX', '^GSPC', '^IXIC', '^VIX'], start='2025-06-01', end='2026-11-28', auto_adjust=True, progress=False)['Close']
    usr = us.pct_change(fill_method=None)
    usr['VIX'] = us['^VIX']
    usr.index = usr.index + pd.Timedelta(days=1)                  # 미국 날짜 d 밤 → 한국 d+1 아침
    rows = []
    days = sorted({p.name for p in (ROOT / 'data' / 'minute_hist').iterdir()} | {p.name for p in (ROOT / 'data' / 'minute').iterdir() if p.name.isdigit()})
    for day in days:
        t = pd.Timestamp(day)
        prev = d.index[d.index < t]
        b = morning(day)
        if b is None or not len(prev):
            continue
        p = prev[-1]
        f = (d.loc[t, 'Adj Close'] / d.loc[t, 'Close']) if t in d.index else 1.0   # 분배금 반영 (그날 가격을 전날 기준에 맞춤)
        base = adj.loc[p]
        row = {'day': day, 'bull': bool(adj.loc[p] > ma120.loc[p]) if not np.isnan(ma120.loc[p]) else None}
        x = usr[usr.index <= t].iloc[-1] if (usr.index <= t).any() else None
        if x is None or (t - usr.index[usr.index <= t][-1]).days > 4:
            continue
        row.update({'soxx': x['SOXX'] * 100, 'spx': x['^GSPC'] * 100, 'ndx': x['^IXIC'] * 100, 'vix': x['VIX']})
        open_ = b['open'].iloc[0]
        row['0900'] = (open_ * f / base - 1) * 100
        for hm in TIMES[1:]:
            c = b[b.index <= hm]['close']
            row[hm] = (c.iloc[-1] * f / base - 1) * 100 if len(c) else np.nan
        row['high'] = (b['high'].max() * f / base - 1) * 100
        row['high_at'] = b['high'].idxmax()
        rows.append(row)
    t = pd.DataFrame(rows)
    t.to_csv(RESEARCH / 'overnight_exit_timing.csv', index=False, encoding='utf-8')
    pd.set_option('display.width', 250)
    print(f'{len(t)}일 ({t.day.min()} ~ {t.day.max()}), 상승장 {int(t.bull.sum())}일')

    def table(g, label):
        out = g[TIMES + ['high']].mean().round(2)
        out['n'] = len(g)
        out['10:00>시가'] = round((g['1000'] > g['0900']).mean() * 100)
        out['최고 시각(중앙)'] = sorted(g['high_at'])[len(g) // 2] if len(g) else ''
        out['09:30 전 최고 비율'] = round((g['high_at'] < '0930').mean() * 100)
        return out.rename(label)

    print('\n== SOXX 밤사이 구간별: 매도 시각마다 전날 종가 대비 평균 수익(%)')
    t['soxx_b'] = pd.cut(t['soxx'], [-100, -3, -1, 0, 1, 3, 100], labels=['≤-3%', '-3~-1', '-1~0', '0~1', '1~3', '>3%'])
    print(pd.concat([table(g, k) for k, g in t.groupby('soxx_b', observed=True)], axis=1).T.to_string())
    down = t[t['soxx'] <= -1]
    print('\n== SOXX -1% 이하인 날을 상승장/하락장으로')
    print(pd.concat([table(g, '상승장' if k else '하락장') for k, g in down.groupby('bull')], axis=1).T.to_string())
    print('\n== S&P500 구간별 (참고)')
    t['spx_b'] = pd.cut(t['spx'], [-100, -1, 0, 1, 100], labels=['≤-1%', '-1~0', '0~1', '>1%'])
    print(pd.concat([table(g, k) for k, g in t.groupby('spx_b', observed=True)], axis=1).T.to_string())
    print('\n== VIX(전날 밤) 구간별 (참고)')
    t['vix_b'] = pd.cut(t['vix'], [0, 20, 25, 100], labels=['<20', '20~25', '≥25'])
    print(pd.concat([table(g, k) for k, g in t.groupby('vix_b', observed=True)], axis=1).T.to_string())
    print('\n== 시가 대비 그 뒤: 갭이 -1% 넘게 빠진 날 / 갭이 +1% 넘게 오른 날, 매도 시각별 (시가 대비 %)')
    for name, g in [('갭 ≤ -1%', t[t['0900'] <= -1]), ('갭 ≥ +1%', t[t['0900'] >= 1]), ('전체', t)]:
        rel = g[TIMES].sub(g['0900'], axis=0).mean().round(2)
        print(f'{name:<10} n={len(g):>3}  ' + '  '.join(f'{k}:{v:+.2f}' for k, v in rel.items()))


if __name__ == '__main__':
    main()

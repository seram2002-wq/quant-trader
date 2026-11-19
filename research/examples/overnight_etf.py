"""밤사이 보유 (KODEX 200을 종가에 사서 다음 날 시가에 팔기) 백테스트

    python -m research.examples.overnight_etf

data/research/intraday/069500_1d.csv (tools/fetch_research_data.py가 받음)를 쓴다.
분배금은 Adj Close로 반영. 왕복 비용별로 탐색·검증 구간 결과를 보여 준다.
2026-11-19 결과: 왕복 0.03%에서 탐색 +3.0%, 검증 +6.3% (기준 0.7%p 미달), 0.02%면 통과
"""
from pathlib import Path

import pandas as pd

from research.engine import stats_of

FILE = Path(__file__).resolve().parents[2] / 'data' / 'research' / 'intraday' / '069500_1d.csv'

if __name__ == '__main__':
    d = pd.read_csv(FILE, index_col=0)
    d.index = pd.to_datetime(d.index, utc=True).tz_convert('Asia/Seoul').tz_localize(None).normalize()
    d = d[(d['Open'] > 0) & (d['Volume'] > 0)].sort_index()
    adj = d['Adj Close'] / d['Close']
    overnight = (d['Open'] * adj) / (d['Close'].shift(1) * adj.shift(1)) - 1
    hold = d['Adj Close'].pct_change()
    print(f"밤사이 연 {overnight.mean() * 252:+.1%}, 장중 연 {(d['Close'] / d['Open'] - 1).mean() * 252:+.1%} (비용 전)")
    for cost in (0, 0.0002, 0.0003, 0.0005):
        out = []
        for a, b, name in (('2012', '2019', '탐색'), ('2020', '2024', '검증')):
            s = stats_of((1 + overnight.loc[a:b].fillna(0) - cost).cumprod())
            h = stats_of((1 + hold.loc[a:b].fillna(0)).cumprod())
            out.append(f"{name} {s['cagr']:+.1%} 낙폭 {s['mdd']:.0%} (그냥 보유 {h['cagr']:+.1%})")
        print(f'왕복 {cost * 100:.2f}% | ' + ' | '.join(out))

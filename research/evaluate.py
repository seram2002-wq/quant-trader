"""채택 기준으로 판정하기 (README "실험 전략 채택 기준")

    from research.evaluate import judge
    judge(p, score, name='내 전략')          # 탐색·검증 구간, 6개 설정으로 판정하고 표를 출력

기준 (2026-11-19)
    - 탐색 구간: 연 수익률이 코스피 이상, 최대 낙폭이 코스피보다 작을 것
    - 검증 구간: 연 수익률이 코스피 + 5%p 이상, 최대 낙폭이 코스피보다 작을 것
    - 설정 하나만 보지 않는다: 종목 범위(150·200·300) × 종목 수(20·30) 6개의 중앙값으로 판정
    - 2025년 이후는 마지막 확인용. 규칙을 고르는 동안 보지 않는다 (final=True로 한 번만)
"""
import numpy as np
import pandas as pd

from research.engine import backtest, equal_weight, stats_of

SEARCH = ('2012-01-01', '2019-12-31')
VALID = ('2020-01-01', '2024-12-31')
FINAL = ('2025-01-01', '2099-12-31')
GRID = [(u, n) for u in (150, 200, 300) for n in (20, 30)]


def passes(res, kospi, extra=0.0):
    return res['cagr'] >= kospi['cagr'] + extra and res['mdd'] > kospi['mdd']


def judge(p, score, name='전략', search=SEARCH, valid=VALID, grid=GRID, final=False, **kw):
    """탐색·검증 구간에서 6개 설정을 돌려 판정. kw는 backtest()로 넘김 (every, neutral 등)"""
    periods = [('탐색', search, 0.0), ('검증', valid, 0.05)]
    if final:
        periods = [('시험', FINAL, 0.05)]
    rows, verdict = [], []
    for label, (a, b), extra in periods:
        k = stats_of(p.kospi.loc[a:b])
        ew = equal_weight(p, a, b).stats
        res = [backtest(p, score, a, b, size=u, n=n, **kw).stats for u, n in grid]
        med = {key: float(np.median([r[key] for r in res])) for key in ('cagr', 'mdd', 'sharpe')}
        ok = passes(med, k, extra)
        verdict.append(ok)
        rows.append({'구간': f'{label} {a[:4]} ~ {b[:4]}',
                     '전략 (중앙값)': f"{med['cagr']:+.1%}, 낙폭 {med['mdd']:.0%}, 샤프 {med['sharpe']:.2f}",
                     '설정별 연 수익률': ' / '.join(f"{r['cagr']:+.1%}" for r in res),
                     '코스피': f"{k['cagr']:+.1%}, 낙폭 {k['mdd']:.0%}",
                     '상위 200 동일 비중': f"{ew['cagr']:+.1%}, 낙폭 {ew['mdd']:.0%}",
                     '기준': f"코스피{' + 5%p' if extra else ''} 이상, 낙폭 더 작게",
                     '통과': '예' if ok else '아니요'})
    table = pd.DataFrame(rows)
    print(f'\n== {name}')
    print(table.to_string(index=False))
    print('판정:', '통과' if all(verdict) else '탈락')
    return table, all(verdict)


def to_markdown(table, name, note=''):
    """judge() 결과를 md 문자열로 (results/나 docs/에 저장할 때)"""
    lines = [f'## {name}\n', note + '\n' if note else '',
             '| ' + ' | '.join(table.columns) + ' |', '|' + '---|' * len(table.columns)]
    for _, r in table.iterrows():
        lines.append('| ' + ' | '.join(str(v) for v in r.values) + ' |')
    return '\n'.join(lines) + '\n'

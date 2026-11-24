"""논문 공개 알파 7개 + 시장 국면 장치 — 2026-11-23

    python -m research.examples.paper_alphas_overlay

11절(paper_alphas.py)의 알파 7개에 13절(drawdown_overlay.py)의 장치를 그대로 붙인다. 아래는 결과를 보기 전에 고정.
    알파·부호  : paper_alphas.py와 같음 (부호는 탐색 구간 10일 뒤 수익률 순위 IC로)
    매매       : 10거래일마다 교체, 업종 중립 없음
    장치       : 코스피가 120일선 아래인 날 다음 날부터 주식 비중 50%, 비중을 바꿀 때 매매 비용
    판정       : judge()와 같은 기준 (탐색 2012 ~ 2019, 검증 2020 ~ 2024, 범위 150·200·300 × 20·30종목 중앙값)
    7개 모두 시험한다. 11절 검증 결과를 보고 좋았던 것만 고르면 검증 구간으로 후보를 고르는 셈이 되기 때문
주의: 이 알파들의 검증 구간 성적은 11절에서 이미 봤다. 통과하더라도 가상 장부로 앞으로의 성적을 확인하기 전까지는 채택하지 않는다
시험 횟수: 후보 7개 × 1회 (지금까지 16개 + 7 = 23개)
2025년 이후는 불러오지 않는다
"""
import numpy as np
import pandas as pd

from research import factors as f
from research.data import load_panel
from research.engine import backtest, stats_of
from research.evaluate import GRID, SEARCH, VALID, passes
from research.examples.drawdown_overlay import MA, overlay
from research.examples.paper_alphas import HORIZON, alphas, rank_ic

WEIGHT = 0.5

if __name__ == '__main__':
    p = load_panel('2010-06-01', VALID[1])                    # 2025년 이후는 불러오지 않음
    down = p.kospi < p.kospi.rolling(MA, min_periods=MA).mean()
    signed = {}
    for name, score in alphas(p).items():
        signed[name] = score if rank_ic(p, score, *SEARCH) >= 0 else -score
    signed['7 1~6 같은 비중'] = f.combine(*signed.values())
    rows = []
    for name, score in signed.items():
        row, ok_all = {'알파': name}, True
        for label, (a, b), extra in (('탐색', SEARCH, 0.0), ('검증', VALID, 0.05)):
            base, over = [], []
            for size, n in GRID:
                eq = backtest(p, score, a, b, size=size, n=n, every=HORIZON).equity
                base.append(stats_of(eq))
                over.append(stats_of(overlay(eq, down.reindex(eq.index), WEIGHT)))
            med = {k: float(np.median([r[k] for r in over])) for k in ('cagr', 'mdd')}
            bmed = {k: float(np.median([r[k] for r in base])) for k in ('cagr', 'mdd')}
            ok = passes(med, stats_of(p.kospi.loc[a:b]), extra)
            ok_all &= ok
            row[f'{label} 장치 없음'] = f"{bmed['cagr']:+.1%}, {bmed['mdd']:.0%}"
            row[f'{label} 장치'] = f"{med['cagr']:+.1%}, {med['mdd']:.0%}" + ('' if ok else ' ✗')
        row['판정'] = '통과' if ok_all else '탈락'
        rows.append(row)
        print(row, flush=True)
    print('\n== 요약 (통과선: 탐색 연 +2.7% 이상·낙폭 -26%보다 작게 / 검증 연 +7.0% 이상·낙폭 -36%보다 작게. ✗ = 그 구간 미달)')
    print(pd.DataFrame(rows).to_string(index=False))

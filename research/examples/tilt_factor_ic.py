"""3단계 1b: 대장주 바구니에서 기본 팩터의 실제 업종 중립 순위 IC (탐색 구간만) — 2026-11-24

    python -m research.examples.tilt_factor_ic

1a의 가짜 신호와 같은 정의·같은 바구니·같은 시점으로 실제 팩터를 잰다 (마이너가 닿아야 할 현실적인 수준)
팩터 (방향은 통상 쓰는 대로 고정, 결과를 보고 뒤집지 않음)
    모멘텀 12-1, 단기 반전 5일·21일, 저변동성 250일, 가치 1/PBR, 이익 수익률 1/PER (거래소 월말 자료)
IC       = 팩터와 업종 안 상대 수익(h일 미래 수익 - 같은 업종 평균)의 순위 상관, h거래일마다 (겹치지 않음)
1등-꼴찌 = 업종마다 팩터 1등과 꼴찌의 상대 수익 차 평균 (교체 1번당. 기울이기가 실제로 버는 몫)
A 2012 ~ 2015 / B 2016 ~ 2019. 검증 구간(2020 ~ 2024)은 불러오지 않는다
결과: data/research/tilt_factor_ic.csv
"""
import numpy as np
import pandas as pd

from research.data import RESEARCH, load_panel
from research.examples.required_ic import forward
from research.examples.tilt_required_ic import HS, START, baskets, plan
from research.factors import low_volatility, momentum, reversal

HALVES = {'A': ('2012-01-01', '2015-12-31'), 'B': ('2016-01-01', '2019-12-31')}

if __name__ == '__main__':
    p = load_panel(START, '2019-12-31')
    p.add_krx()
    bs = baskets(p)
    pos = lambda d: p.dates.searchsorted(pd.Timestamp(d))                          # noqa: E731
    factors = {'모멘텀 12-1': momentum(p), '반전 5일': reversal(p, 5), '반전 21일': reversal(p, 21),
               '저변동성 250일': low_volatility(p, 250),
               '가치 1/PBR': 1 / p.krx['pbr'].where(p.krx['pbr'] > 0),
               '이익 수익률 1/PER': 1 / p.krx['per'].where(p.krx['per'] > 0)}
    rows = []
    for h in HS:
        fwd = forward(p, h)
        for name, F in factors.items():
            F = F.reindex(index=p.dates, columns=p.codes)
            _, diag = plan(p, bs, h, lambda s, codes, rel: F.iloc[s].reindex(codes), fwd)
            d = pd.DataFrame(diag, columns=['T', 'ic', 'spread'])
            for half, (a, b) in HALVES.items():
                x = d[(d['T'] >= pos(a)) & (d['T'] < pos(b) + 1)].dropna()
                rows.append({'h': h, '팩터': name, '구간': half, '횟수': len(x), 'IC': x['ic'].mean(),
                             't': x['ic'].mean() / x['ic'].std() * np.sqrt(len(x)) if len(x) > 1 else np.nan,
                             'IC>0 비율': (x['ic'] > 0).mean(), '1등-꼴찌': x['spread'].mean()})
        print(f'h {h} 끝', flush=True)
    df = pd.DataFrame(rows)
    df.to_csv(RESEARCH / 'tilt_factor_ic.csv', index=False, encoding='utf-8')
    pd.set_option('display.width', 200)
    print(df.round(4).to_string(index=False))

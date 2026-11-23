"""논문 공개 알파 6개를 한국 데이터로 시험 — 2026-11-23

    python -m research.examples.paper_alphas

출처: Shi, Duan, Li "Navigating the Alpha Jungle: An LLM-Powered MCTS Framework for Formulaic Factor
Mining" (arXiv 2505.11122v1, 2025-05) 부록 표 6 "Ours" 공식 6개. 중국 CSI300·CSI1000에서 찾은 공식을
숫자 하나 바꾸지 않고 한국 일봉에 그대로 넣는다. 결과를 보기 전에 아래 규칙을 고정했다.

공식 (연산자는 논문 표 2. 모두 종목별 시계열 계산)
    1. Zscore(Ma(close - vwap, 20), 30)
    2. Std(Pct(vwap, 20), 25) * Sum(volume, 40) / volume
    3. Corr(close, volume, 50) * Zscore(Ma(close - vwap, 30), 40)
    4. Diff(Ma(volume, 20), 3) / Ma(volume, 60)
    5. Corr(Pct(close, 10), Pct(volume, 10), 10) * Corr(Pct(close, 30), Pct(volume, 30), 30) * Skew(volume, 20)
    6. Ma(Corr(volume, close, 20) * Skew(high - low, 20), 10)
    7. 1 ~ 6을 부호를 맞춘 뒤 같은 비중으로 섞은 것 (논문은 여러 알파를 모델로 섞어 썼다)

고정한 규칙
    가격     : 수정 가격 (액면분할 반영). vwap = 그날 거래대금 / 거래량, 같은 수정 계수로 맞춤
    부호     : 논문은 알파를 LightGBM 입력으로 써서 "클수록 좋은지"가 정해져 있지 않다.
               탐색 구간(2012 ~ 2019)의 10일 뒤 수익률 순위 IC 평균의 부호로 정하고 검증 구간에도 그대로 쓴다
               (탐색 구간 성적은 부호를 고른 만큼 낙관적이다. 판단은 검증 구간으로)
    매매     : research 기본 엔진, 10거래일마다 교체 (논문의 10일 예측 기간에 맞춤), 업종 중립 없음 (논문과 같게)
    판정     : judge() 기본. 탐색 2012 ~ 2019, 검증 2020 ~ 2024, 범위 150·200·300 × 20·30종목 중앙값
    2025년 이후는 불러오지 않는다
시험 횟수: 후보 7개 × 1회 (스윙 후보 9개에 더해 16개째)
결과 (모두 탈락): docs/backtest_summary.md 11절
"""
import numpy as np
import pandas as pd

from research.data import load_panel
from research.evaluate import SEARCH, VALID, judge
from research import factors as f
from research.examples.swing_event import load_high_low

HORIZON = 10


def zscore(x, t):
    return (x - x.rolling(t, min_periods=t).mean()) / x.rolling(t, min_periods=t).std()


def pct(x, t):
    return x / x.shift(t) - 1


def corr(x, y, t):
    return x.rolling(t, min_periods=t).corr(y)


def alphas(p):
    fac = p.idx / p.close                                   # 그날의 수정 계수
    close = p.idx
    vwap = (p.amount / p.volume.where(p.volume > 0)) * fac
    volume = (p.volume / fac).where(p.volume > 0)
    hi, lo = load_high_low(p)
    rng = (hi - lo) * fac
    out = {
        '1 Zscore(Ma(close-vwap,20),30)': zscore((close - vwap).rolling(20).mean(), 30),
        '2 Std(Pct(vwap,20),25)*Sum(volume,40)/volume':
            pct(vwap, 20).rolling(25).std() * volume.rolling(40).sum() / volume,
        '3 Corr(close,volume,50)*Zscore(Ma(close-vwap,30),40)':
            corr(close, volume, 50) * zscore((close - vwap).rolling(30).mean(), 40),
        '4 Diff(Ma(volume,20),3)/Ma(volume,60)':
            volume.rolling(20).mean().diff(3) / volume.rolling(60).mean(),
        '5 Corr(Pct10)*Corr(Pct30)*Skew(volume,20)':
            corr(pct(close, 10), pct(volume, 10), 10) * corr(pct(close, 30), pct(volume, 30), 30)
            * volume.rolling(20).skew(),
        '6 Ma(Corr(volume,close,20)*Skew(high-low,20),10)':
            (corr(volume, close, 20) * rng.rolling(20).skew()).rolling(10).mean(),
    }
    return {k: v.replace([np.inf, -np.inf], np.nan) for k, v in out.items()}


def rank_ic(p, score, a, b):
    """하루하루 단면 순위 상관(score, 10일 뒤 수익률)의 평균. 엔진과 같게 2일 늦춘 점수"""
    fwd = p.idx.shift(-HORIZON) / p.idx - 1
    ok = p.eligible & (p.amount20 >= 1e9)
    s = score.shift(2).where(ok).loc[a:b].rank(axis=1)
    r = fwd.where(ok).loc[a:b].rank(axis=1)
    return s.corrwith(r, axis=1).mean()


def self_check():
    x = pd.DataFrame({'a': [1., 2, 3, 4, 5, 6]})
    assert abs(zscore(x, 3)['a'].iloc[-1] - 1.0) < 1e-12           # (6 - 5) / 1
    assert abs(pct(x, 2)['a'].iloc[-1] - (6 / 4 - 1)) < 1e-12
    assert abs(corr(x, x * 2, 3)['a'].iloc[-1] - 1.0) < 1e-12


if __name__ == '__main__':
    self_check()
    p = load_panel('2010-06-01', VALID[1])                         # 2025년 이후는 불러오지 않음
    signed, rows = {}, []
    for name, score in alphas(p).items():
        ic_s = rank_ic(p, score, *SEARCH)
        sign = 1.0 if ic_s >= 0 else -1.0
        signed[name] = score * sign
        rows.append({'알파': name, '탐색 순위IC': f'{ic_s:+.4f}', '부호': '+' if sign > 0 else '-',
                     '검증 순위IC (부호 반영)': f'{sign * rank_ic(p, score, *VALID):+.4f}'})
    print(pd.DataFrame(rows).to_string(index=False))
    signed['7 1~6 같은 비중'] = f.combine(*signed.values())
    for name, score in signed.items():
        judge(p, score, name=name, every=HORIZON)

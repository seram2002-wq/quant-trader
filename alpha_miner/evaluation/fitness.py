"""후보 수식 평가: 탐색 구간(2012 ~ 2019) 안에서만, 두 단계로 거른다

    A 학습 2012 ~ 2015 / B 선택 2016 ~ 2019  (2020년 이후는 마이너가 불러오지도 않음)

1단계 맨 위 초과 수익 (빠름): 10거래일마다 점수 상위 20종목을 새로 고를 때, 그 20종목의 10일 수익이
    같은 기간 코스피보다 얼마나 높은지에서 왕복 비용 x 바뀐 비율을 뺀 값 (교체 1번당 평균).
    부호는 A에서 이 값이 큰 쪽으로 정하고 B에는 그대로 쓴다. A, B 모두 EX_MIN 초과여야 2단계로.
    15절에는 IC로 걸렀고(17절: IC가 플러스여도 맨 위가 가장 나쁠 수 있음), 18절에는 상위 200 평균 대비로 걸렀다
    (2016 ~ 2019는 상위 200 평균이 코스피보다 10일당 0.22%p 낮아서 1단계 통과 13개가 모두 2단계에서 짐). IC는 참고로만 기록
2단계 구조 백테스트: 12·13절에서 문턱이 가장 낮았던 구조 그대로
    시가총액 상위 200 중 20종목, 10거래일마다 교체, 코스피가 120일선 아래면 주식 비중 50%, 비용 config
    A, B 모두 연 수익이 코스피 이상이고 낙폭이 코스피보다 작아야 합격
다양성: 합격 후보끼리 점수의 단면 순위 상관이 DIVERSITY_MAX 이상이면 중복으로 본다 (alpha_pool에서 판단)
"""
import numpy as np

from alpha_miner.engine.ast_parser import AlphaASTParser, AlphaSyntaxError
from alpha_miner.evaluation.metrics import ic_series, top_excess, turnover, universe
from research.engine import backtest, stats_of
from research.examples.drawdown_overlay import MA, overlay
from research.examples.required_ic import LAG, forward

HALVES = {'A': ('2012-01-01', '2015-12-31'), 'B': ('2016-01-01', '2019-12-31')}
HORIZON = 10
EX_MIN = 0.0                                     # 교체 1번당 비용 뒤 초과 수익이 0보다 커야 함
SIZE, N, WEIGHT = 200, 20, 0.5
MIN_NAMES = 100


def coverage_start(score, mask, a, b, min_names=MIN_NAMES):
    """[a, b] 안에서 평가 종목 중 점수가 있는 종목이 min_names개 이상인 첫날 (없으면 None)"""
    n = (score.notna() & mask).loc[a:b].sum(axis=1)
    ok = n[n >= min_names]
    return ok.index[0] if len(ok) else None


class Evaluator:
    def __init__(self, p, feats):
        self.p, self.parser = p, AlphaASTParser(feats)
        self.mask = universe(p, SIZE)
        self.fwd = forward(p, HORIZON)
        self.kospi_fwd = p.kospi.shift(-(LAG + HORIZON)) / p.kospi.shift(-LAG) - 1   # 종목 수익과 같은 기간
        self.down = p.kospi < p.kospi.rolling(MA, min_periods=MA).mean()

    def score(self, formula, sign=1.0):
        """부호를 맞춘 점수 (날짜 x 종목)"""
        return self.parser.evaluate(formula).reindex(self.p.dates) * sign

    def _excess(self, score, half):
        a, b = HALVES[half]
        return top_excess(score.loc[a:b], self.fwd.loc[a:b], self.mask.loc[a:b], N, HORIZON, MIN_NAMES,
                          bench=self.kospi_fwd).mean()

    def evaluate(self, formula):
        """{'status': error|weak_top|failed|passed, 'reason', 지표...}"""
        try:
            raw = self.score(formula)
        except AlphaSyntaxError as e:
            return {'status': 'error', 'reason': str(e)}
        ex_a = {s: self._excess(raw * s, 'A') for s in (1.0, -1.0)}
        if not all(np.isfinite(v) for v in ex_a.values()):
            return {'status': 'error', 'reason': f'A 구간에 점수가 있는 종목이 {MIN_NAMES}개 이상인 날이 없습니다 (값이 대부분 NaN)'}
        sign = max(ex_a, key=ex_a.get)
        ex_b = self._excess(raw * sign, 'B')
        if not np.isfinite(ex_b):
            return {'status': 'error', 'reason': f'B 구간에 점수가 있는 종목이 {MIN_NAMES}개 이상인 날이 없습니다'}
        ic = {k: sign * ic_series(raw.loc[a:b], self.fwd.loc[a:b], self.mask.loc[a:b]).mean() for k, (a, b) in HALVES.items()}
        out = {'sign': sign, 'ex_a': ex_a[sign], 'ex_b': ex_b, 'ic_a': ic['A'], 'ic_b': ic['B'],
               'turnover': turnover(raw * sign, self.mask, N)}
        if min(out['ex_a'], out['ex_b']) <= EX_MIN:
            return {**out, 'status': 'weak_top',
                    'reason': f"상위 {N}종목 10일 코스피 대비 초과 수익(비용 뒤) A {out['ex_a']:+.2%} / B {out['ex_b']:+.2%} (둘 다 플러스 필요)"}
        ok, parts = True, []
        for k, (a, b) in HALVES.items():
            a = coverage_start(raw, self.mask, a, b)                  # 거래소 자료처럼 늦게 시작하는 피처
            if a is None:
                return {**out, 'status': 'error', 'reason': f'{k} 구간에 점수가 있는 종목이 {MIN_NAMES}개 미만입니다'}
            eq = backtest(self.p, raw * sign, a, b, size=SIZE, n=N, every=HORIZON).equity
            s = stats_of(overlay(eq, self.down.reindex(eq.index), WEIGHT))
            kos = stats_of(self.p.kospi.loc[a:b])                     # 같은 기간의 코스피와 비교
            out[f'cagr_{k.lower()}'], out[f'mdd_{k.lower()}'] = s['cagr'], s['mdd']
            ok &= s['cagr'] >= kos['cagr'] and s['mdd'] > kos['mdd']
            parts.append(f"{k}({str(a)[:7]}~) {s['cagr']:+.1%}, 낙폭 {s['mdd']:.0%} (코스피 {kos['cagr']:+.1%}, {kos['mdd']:.0%})")
        out['reason'] = '구조 백테스트 ' + ' / '.join(parts)
        return {**out, 'status': 'passed' if ok else 'failed'}

    def correlation(self, s1, s2, step=20):
        """두 점수의 단면 순위 상관 평균 (상위 200 안, step일마다 표본)"""
        rows = self.p.dates[(self.p.dates >= HALVES['A'][0]) & (self.p.dates <= HALVES['B'][1])][::step]
        a, b = s1.loc[rows].where(self.mask.loc[rows]), s2.loc[rows].where(self.mask.loc[rows])
        return a.rank(axis=1).corrwith(b.rank(axis=1), axis=1).mean()

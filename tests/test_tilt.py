"""3단계 1a 모의 계산: 기울이기 수익과, 1등·꼴찌가 그대로면 거래하지 않는지

    python -m unittest tests.test_tilt
"""
import unittest
from types import SimpleNamespace

import numpy as np
import pandas as pd

from research.examples.drawdown_overlay import BUY, SELL
from research.examples.tilt_required_ic import MAX_TILT, simulate


class Simulate(unittest.TestCase):
    def setUp(self):
        codes = ['A', 'B', 'C']
        self.p = SimpleNamespace(dates=pd.bdate_range('2020-01-01', periods=7), col={c: i for i, c in enumerate(codes)})
        self.R = np.tile([0.01, 0.0, -0.01], (7, 1))           # A +1%, B 0, C -1% 매일
        self.mc = np.ones((7, 3))                              # 시가총액 같음 → 바구니 수익 0
        sect = pd.Series({'A': 'X', 'B': 'X', 'C': 'Y'})
        roles = {'X': ('A', 'B'), 'Y': ('C', 'C')}
        self.steps = [(0, codes, sect, roles), (3, codes, sect, dict(roles))]   # 3일째 다시 맞춤, 순위 같음

    def test_s2_tilt_and_no_retrade(self):
        strat, base = simulate(self.p, self.steps, 'S2', 1.0, self.R, self.mc, np.zeros(7))
        tilt = MAX_TILT * 0.01                                 # A +5%p, B -5%p (k·b = 1/3 > 상한 5%p)
        self.assertAlmostEqual(strat[1], tilt - (BUY + MAX_TILT * BUY + MAX_TILT * SELL))   # 처음 바구니·기울이기 매수
        self.assertAlmostEqual(strat[4], tilt)                 # 1등·꼴찌 그대로 → 비용 없음
        self.assertAlmostEqual(base[4], 0.0)

    def test_s1_core_satellite(self):
        core = np.full(7, 0.002)
        strat, _ = simulate(self.p, self.steps, 'S1', 0.5, self.R, self.mc, core)
        self.assertAlmostEqual(strat[1], 0.5 * 0.002 + 0.5 * 0.0 - 0.5 * BUY)   # 위성: A(+1%)와 C(-1%) 평균
        self.assertAlmostEqual(strat[4], 0.001)

    def test_s1_trades_only_changed_sector(self):
        steps = [self.steps[0], (3, self.steps[1][1], self.steps[1][2], {'X': ('B', 'A'), 'Y': ('C', 'C')})]
        strat, _ = simulate(self.p, steps, 'S1', 0.5, self.R, self.mc, np.zeros(7))
        self.assertAlmostEqual(strat[4], 0.5 * (0.0 - 0.01) / 2 - 0.5 * (1 / 2) * (BUY + SELL))   # X만 교체


if __name__ == '__main__':
    unittest.main()

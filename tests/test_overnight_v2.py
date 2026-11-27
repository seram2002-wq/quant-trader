"""밤사이 보유 v2: 전날 밤 SOXX에 따라 아침 매도 시점

    python -m unittest tests.test_overnight_v2
"""
import unittest
from types import SimpleNamespace

from strategies.overnight_etf import OvernightEtfV2


def strategy(soxx):
    s = OvernightEtfV2()
    s.log = lambda *a: None
    client = SimpleNamespace(get_us_change=(lambda *a: soxx) if not isinstance(soxx, Exception)
                             else (lambda *a: (_ for _ in ()).throw(soxx)))
    return s, client


class MorningReason(unittest.TestCase):
    def test_soxx_up_waits_until_0902(self):
        s, c = strategy(0.012)
        q = {'open': 75000, 'price': 75100}
        self.assertIsNone(s.morning_reason(c, q, 900, '기본'))
        self.assertIsNone(s.morning_reason(c, q, 901, '기본'))
        self.assertIn('9:02 매도', s.morning_reason(c, q, 902, '기본'))

    def test_soxx_down_waits_for_plus_1pct_or_1100(self):
        s, c = strategy(-0.02)
        self.assertIsNone(s.morning_reason(c, {'open': 75000, 'price': 75600}, 930, '기본'))      # +0.8%
        self.assertIn('반등', s.morning_reason(c, {'open': 75000, 'price': 75750}, 931, '기본'))  # +1.0%
        self.assertIn('못 올라', s.morning_reason(c, {'open': 75000, 'price': 74000}, 1100, '기본'))

    def test_no_soxx_sells_at_once(self):
        s, c = strategy(RuntimeError('시세 없음'))
        self.assertEqual(s.morning_reason(c, {'open': 75000, 'price': 74000}, 900, '기본'), '기본 (SOXX 조회 실패)')


if __name__ == '__main__':
    unittest.main()

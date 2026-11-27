"""밤사이 보유 그림자: 시초가 +0.5% / +1% 반등 매도와 실제 매도 비교 한 줄

    python -m unittest tests.test_overnight_shadow
"""
import unittest

from tools.overnight_shadow import rebound_sell, row_for

BARS = [('0900', 10000, 9950), ('0901', 9950, 10060), ('0902', 10060, 10120), ('1059', 10120, 10080)]


class Rebound(unittest.TestCase):
    def test_first_bar_over_target(self):
        self.assertEqual(rebound_sell(BARS, 0.005), ('0901', 10060))       # 시초가 10000 × 1.005 = 10050 넘은 첫 봉
        self.assertEqual(rebound_sell(BARS, 0.01), ('0902', 10120))
        self.assertEqual(rebound_sell(BARS, 0.02), ('1059', 10080))        # 못 오르면 10:59 종가
        self.assertIsNone(rebound_sell([], 0.01))

    def test_row(self):
        r = row_for('20261127', -1.2, 0.4, {'time': '2026-11-27 09:00:24', 'qty': '10', 'price': '10000'}, BARS)
        self.assertEqual((r['soxx_down'], r['diff_a05_won'], r['diff_a10_won']), (1, 600, 1200))
        r = row_for('20261127', 0.5, 0.4, {'time': '2026-11-27 09:00:24', 'qty': '10', 'price': '10000'}, [])
        self.assertEqual((r['soxx_down'], r['diff_a10_won']), (0, ''))


if __name__ == '__main__':
    unittest.main()

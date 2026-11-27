"""밤사이 보유 그림자: 10:30 매도와 실제 매도 비교 한 줄

    python -m unittest tests.test_overnight_shadow
"""
import unittest

from tools.overnight_shadow import row_for


class Row(unittest.TestCase):
    def test_rule_day(self):
        sell = {'time': '2026-11-25 09:00:02', 'qty': '120', 'price': '75295.0'}
        r = row_for('20261125', -1.48, sell, 75800.0)
        self.assertEqual((r['rule'], r['diff_won']), (1, round((75800 - 75295) * 120)))
        self.assertAlmostEqual(r['diff_pct'], round((75800 / 75295 - 1) * 100, 3))

    def test_no_bar(self):
        r = row_for('20261126', 0.3, {'time': '2026-11-26 09:00:02', 'qty': '129', 'price': '73140'}, None)
        self.assertEqual((r['rule'], r['diff_won']), (0, ''))


if __name__ == '__main__':
    unittest.main()

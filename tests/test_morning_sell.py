"""다음 날 아침 매도: 오늘 첫 거래 전(현재가가 아직 전날 종가)에는 팔지 않는다

    python -m unittest tests.test_morning_sell
"""
import unittest
from datetime import datetime
from types import SimpleNamespace

import run


class MorningSell(unittest.TestCase):
    def runner(self, quote):
        r = run.Runner.__new__(run.Runner)                  # 장부·API 없이 morning_sell만
        r.broker = SimpleNamespace(positions={'069500': {'time': '2026-11-26 15:18:02', 'name': 'KODEX 200'}})
        r.quotes = SimpleNamespace(get=lambda code: quote)
        r.strategy = SimpleNamespace(morning_exit=0)
        r.prices, r.sold = {}, []
        r.sell = lambda code, price, reason: r.sold.append(price)
        return r

    def test_waits_for_first_trade(self):
        r = self.runner({'price': 80630, 'volume': 0})       # 09:00:02, 아직 전날 종가
        r.morning_sell(datetime(2026, 11, 27, 9, 0, 2))
        self.assertEqual(r.sold, [])
        r.quotes = SimpleNamespace(get=lambda code: {'price': 77370, 'volume': 152074})
        r.morning_sell(datetime(2026, 11, 27, 9, 0, 7))
        self.assertEqual(r.sold, [77370])


if __name__ == '__main__':
    unittest.main()

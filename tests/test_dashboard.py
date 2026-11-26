"""웹 전광판의 하루 손익 곡선: 실현 + 평가, 전날부터 들고 온 종목

    python -m unittest tests.test_dashboard
"""
import unittest

import pandas as pd

from tools.dashboard import day_pnl


def row(day, hhmm, side, code, qty, amount, fee, profit=None):
    return {'day': day, 'hhmm': hhmm, 'side': side, 'code': code, 'qty': qty, 'amount': amount, 'fee': fee,
            'profit': profit}


class DayPnl(unittest.TestCase):
    def test_carried_bought_and_sold(self):
        t = pd.DataFrame([
            row('20261124', '1518', 'BUY', 'E', 10, 1000, 0),                 # 어제 산 ETF (10주, 100원)
            row('20261125', '0900', 'SELL', 'E', 10, 1100, 0, 100),           # 오늘 9:00 팔아 +100
            row('20261125', '0901', 'BUY', 'A', 2, 200, 0),                   # 오늘 산 종목 (2주, 100원)
        ])
        closes = {'E': pd.Series({'0859': 105}), 'A': pd.Series({'0900': 100, '0901': 100, '0902': 130})}
        self.assertEqual(day_pnl(t, '20261125', closes),
                         [('0859', 50), ('0900', 100), ('0901', 100), ('0902', 160)])


if __name__ == '__main__':
    unittest.main()

"""장 시간 기준 시각: 평소와 수능 날(2026-11-19, 10:00 ~ 16:30)

    python -m unittest discover tests
"""
import csv
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

import config
from trader import disclosures, market
from strategies.close_reversal import CloseReversal
from strategies.overnight_etf import OvernightEtf

NORMAL, SUNEUNG = '20261120', '20261119'


class At(unittest.TestCase):
    def test_normal_day(self):
        self.assertEqual([market.at(x, NORMAL) for x in (0, 5, -60, -30, -15, -10)],
                         [900, 905, 1430, 1500, 1515, 1520])

    def test_suneung_shifts_open_and_close(self):
        self.assertEqual(config.SPECIAL_HOURS[SUNEUNG], (1000, 1630))
        self.assertEqual([market.at(x, SUNEUNG) for x in CloseReversal.buy_window], [1530, 1600])
        self.assertEqual(market.at(config.EXIT_TIME, SUNEUNG), 1615)
        self.assertEqual(market.at(OvernightEtf.morning_exit, SUNEUNG), 1000)    # 개장 전에 팔지 않음

    def test_shift_crosses_hour(self):
        self.assertEqual((market.shift(1530, 1), market.shift(1530, 30), market.shift(1000, -1)),
                         (1531, 1600, 959))


class DisclosureCutOnSpecialDay(unittest.TestCase):
    """수능 날 다음 날에는 전날 16:30 이후 공시만 '장 마감 뒤'로 본다"""

    def test_cut_follows_previous_close(self):
        tmp = Path(tempfile.mkdtemp())
        (tmp / 'dart').mkdir()
        (tmp / 'minute' / SUNEUNG).mkdir(parents=True)
        (tmp / 'minute' / SUNEUNG / '005930.csv').write_text('x')
        with open(tmp / 'dart' / f'{SUNEUNG}.csv', 'w', newline='', encoding='utf-8-sig') as f:
            w = csv.DictWriter(f, fieldnames=['rcept_no', 'rcept_dt', 'stock_code', 'report_nm', 'collected_at'])
            w.writeheader()
            w.writerow({'rcept_no': '1', 'stock_code': '111111', 'report_nm': '유상증자결정',
                        'collected_at': '2026-11-19 16:00:00'})          # 그날은 아직 장중
            w.writerow({'rcept_no': '2', 'stock_code': '222222', 'report_nm': '유상증자결정',
                        'collected_at': '2026-11-19 16:40:00'})
        with mock.patch.object(disclosures, 'DART_DIR', tmp / 'dart'), \
                mock.patch.object(disclosures, 'MINUTE_DIR', tmp / 'minute'):
            bad, _ = disclosures.scan({'111111', '222222'}, datetime(2026, 11, 20, 14, 35))
        self.assertEqual(set(bad), {'222222'})


if __name__ == '__main__':
    unittest.main()

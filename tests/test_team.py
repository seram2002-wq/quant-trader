"""팀 공유 내보내기와 주간 랭킹

    python -m unittest tests.test_team
"""
import csv
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from tools.dashboard import week_rows
from tools.team_export import books, equity, put_row


class Export(unittest.TestCase):
    def test_books_both_config_formats(self):
        bs = books([{'strategy': 'close_reversal.CloseReversal', 'account': 'mock', 'capital': 10_000_000},
                    {'name': '모멘텀 120일/10종목', 'book': 'momentum', 'account': 'mock', 'capital': 100_000_000}])
        self.assertEqual(bs[0], {'book': 'mock_close_reversal', 'label': '모의·장 마감 반전 v1', 'account': 'mock',
                                 'capital': 10_000_000})
        self.assertEqual(bs[1]['book'], 'momentum')
        self.assertEqual(bs[1]['label'], '모의·모멘텀 120일/10종목')

    def test_equity_and_row_replace(self):
        state = {'cash': 1000, 'positions': {'A': {'qty': 2, 'avg_price': 100}}}
        self.assertEqual(equity(state, lambda code, p: 150), (1300, 1000, 300, 1))
        path = Path(tempfile.mkdtemp()) / 'equity.csv'
        put_row(path, {'day': '20261126', 'equity': 1, 'cash': 1, 'holdings': 0, 'positions': 0})
        put_row(path, {'day': '20261125', 'equity': 2, 'cash': 2, 'holdings': 0, 'positions': 0})
        put_row(path, {'day': '20261126', 'equity': 3, 'cash': 3, 'holdings': 0, 'positions': 0})   # 같은 날은 바꿈
        with open(path, encoding='utf-8') as f:
            self.assertEqual([(r['day'], r['equity']) for r in csv.DictReader(f)], [('20261125', '2'), ('20261126', '3')])


class Ranking(unittest.TestCase):
    def test_week_return_uses_last_week_close(self):
        eq = pd.DataFrame({'day': ['20261120', '20261124', '20261127'], 'equity': [1000.0, 1100.0, 1050.0]})
        t = pd.DataFrame({'day': ['20261124', '20261127'], 'side': ['SELL', 'SELL'], 'profit': [100, -50]})
        eq2 = pd.DataFrame({'day': ['20261125'], 'equity': [10_300_000.0]})          # 지난주 기록 없음 → 자금 기준
        t2 = pd.DataFrame(columns=['day', 'side', 'profit'])
        r = week_rows([('세람', 'a', 1000, eq, t), ('동균', 'b', 10_000_000, eq2, t2)], '20261123')
        self.assertEqual(r['weeks'], ['20261123', '20261116'])
        self.assertEqual([x['person'] for x in r['rows']], ['세람', '동균'])
        self.assertAlmostEqual(r['rows'][0]['ret'], 5.0)                               # 1050 / 1000
        self.assertEqual((r['rows'][0]['sells'], r['rows'][0]['win'], r['rows'][0]['worst']), (2, 50.0, -50.0))
        self.assertAlmostEqual(r['rows'][1]['ret'], 3.0)


if __name__ == '__main__':
    unittest.main()

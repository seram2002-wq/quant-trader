"""뉴스 판정 사후 분석: 분봉 맞추기 규칙과 집계 (가짜 파일)

    python -m unittest discover tests
"""
import csv
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

from tools import news_report as nr

DAY = '20261120'


def write(path, fields, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def bars(price):
    """09:00 ~ 09:40 분봉. price(i) = i번째 봉의 (시가, 종가)"""
    return [{'date': DAY, 'time': f'09{i:02d}00', 'open': price(i)[0], 'high': 0, 'low': 0,
             'close': price(i)[1], 'volume': 1, 'value': 1} for i in range(41)]


class Match(unittest.TestCase):
    def setUp(self):
        tmp = Path(tempfile.mkdtemp())
        for p in (mock.patch.object(nr, 'MINUTE_DIR', tmp / 'minute'), mock.patch.object(nr, 'NEWS_DIR', tmp / 'news')):
            p.start()
            self.addCleanup(p.stop)
        f = ['date', 'time', 'open', 'high', 'low', 'close', 'volume', 'value']
        write(tmp / 'minute' / DAY / '000001.csv', f, bars(lambda i: (100 + i, 101 + i)))   # 1분마다 1원씩 오름
        write(tmp / 'minute' / DAY / '069500.csv', f, bars(lambda i: (100, 100)))           # 시장은 그대로
        self.b = nr.load_bars(DAY, '000001')

    def at(self, hhmmss):
        return nr.returns(self.b, pd.Timestamp(f'2026-11-20 {hhmmss}'))

    def test_before_open_starts_at_first_open(self):
        r = self.at('08:30:00')                                       # 시가 100에서 시작, 시간도 09:00부터
        self.assertEqual([round(r[k], 4) for k in nr.COLS], [0.05, 0.15, 0.30, 0.41])

    def test_intraday_uses_last_finished_bar(self):
        r = self.at('09:10:30')                                       # 09:09 봉 종가 110 (09:10 봉은 아직 안 끝남)
        self.assertAlmostEqual(r['5분'], 115 / 110 - 1)               # 09:14 봉 종가
        self.assertAlmostEqual(r['30분'], 140 / 110 - 1)              # 09:39 봉 종가, 마지막 봉 안
        self.assertTrue(pd.isna(self.at('09:20:00')['30분']))         # 09:50은 장 마감 뒤 → 빈칸
        self.assertIsNone(self.at('10:00:00'))                        # 장 마감 뒤 포착

    def test_report_dedupes_and_lists_false_positives(self):
        f = ['time', 'code', 'name', 'verdict', 'keywords', 'title', 'link', 'pub_time']
        row = {'code': '000001', 'name': '에이', 'keywords': '', 'pub_time': ''}
        write(nr.NEWS_DIR / f'{DAY}.csv', f, [
            dict(row, time='2026-11-20 09:10:30', verdict='악재', keywords='횡령', title='에이 횡령', link='l1'),
            dict(row, time='2026-11-20 09:20:00', verdict='악재', keywords='횡령', title='에이 횡령 2', link='l2'),
            dict(row, time='2026-11-20 08:30:00', verdict='호재', keywords='수주', title='에이 수주', link='l3'),
            dict(row, time='2026-11-20 08:30:00', verdict='중립', code='000002', title='비', link='l4'),
        ])
        text = nr.build(nr.read_news())
        self.assertIn('분봉과 맞춘 것 3건, 장 마감 뒤 포착 0건, 그날 분봉 없음 1건', text)
        self.assertIn('| 악재 | 2 | 1 | +4.55% (100%) |', text)            # 같은 날 같은 판정은 처음(09:10) 것만
        self.assertIn('오탐: 악재인데 오른 종목 (1 / 1)', text)
        self.assertIn('[에이 횡령](l1)', text)
        self.assertIn('오탐: 호재인데 내린 종목 (0 / 1)', text)

    def test_no_news_yet(self):
        self.assertIn('아직 data/news/에 기록이 없습니다', nr.build(nr.read_news()))


if __name__ == '__main__':
    unittest.main()

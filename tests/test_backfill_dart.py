"""과거 DART 공시 받기: 요청 한도에서 멈추고, 다시 실행하면 이어받는지 (실제 DART에 요청하지 않음)

    python -m unittest discover tests
"""
import csv
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools import backfill_dart as bf
from tools import collect_dart as cd

ITEM = {'rcept_dt': '', 'stock_code': '005930', 'report_nm': '자기주식취득결정'}
PAGES = {   # (날짜, 유형, 쪽): (상태, 전체 쪽 수, 접수번호들)
    ('20150105', 'B', 1): ('000', 1, ['1']),
    ('20150105', 'I', 1): ('000', 2, ['2']),
    ('20150105', 'I', 2): ('000', 2, ['3']),
    ('20150106', 'B', 1): ('000', 1, ['4']),
    ('20150106', 'I', 1): ('013', None, []),
}


class Backfill(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.dir = Path(tempfile.mkdtemp())
        for p in (mock.patch.object(cd, 'OUT_DIR', self.dir), mock.patch.object(bf.time, 'sleep'),
                  mock.patch.object(bf.requests, 'get', side_effect=self.fake_get)):
            p.start()
            self.addCleanup(p.stop)

    def fake_get(self, url, timeout, params):
        key = (params['bgn_de'], params['pblntf_ty'], params['page_no'])
        self.calls.append(key)
        status, pages, nos = PAGES[key]
        return mock.Mock(json=lambda: {'status': status, 'total_page': pages,
                                       'list': [dict(ITEM, rcept_no=n) for n in nos]})

    def test_stops_at_limit_then_resumes(self):
        saved, calls, why = bf.backfill('k', '20150103', '20150106', max_calls=4)   # 토요일부터
        self.assertEqual((saved, calls), (1, 4))
        self.assertIn('4번', why)
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), ['20150105.csv'])   # 반쯤 받은 06일은 없음
        with open(self.dir / '20150105.csv', encoding='utf-8-sig') as f:
            rows = list(csv.DictReader(f))
        self.assertEqual([r['rcept_no'] for r in rows], ['1', '2', '3'])                # B 1쪽 + I 2쪽
        self.assertEqual({r['collected_at'] for r in rows}, {''})

        self.calls.clear()
        saved, calls, why = bf.backfill('k', '20150103', '20150106', max_calls=10)
        self.assertEqual((saved, calls, why), (1, 2, ''))
        self.assertTrue(all(day == '20150106' for day, _, _ in self.calls))              # 05일은 건너뜀

    def test_dart_limit_error_stops_without_file(self):
        PAGES[('20150107', 'B', 1)] = ('020', None, [])
        self.addCleanup(PAGES.pop, ('20150107', 'B', 1))
        saved, calls, why = bf.backfill('k', '20150107', '20150107')
        self.assertEqual((saved, calls), (0, 1))
        self.assertIn('020', why)
        self.assertFalse((self.dir / '20150107.csv').exists())


if __name__ == '__main__':
    unittest.main()

"""장 마감 반전 v3: 대장주 바구니 규칙, 업종 괴리율 판단과 기록, 사후 분석의 필터 끈 v3

    python -m unittest tests.test_close_reversal_v3
"""
import tempfile
import time
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

import pandas as pd

from strategies import close_reversal as cr
from tools import v3_report
from trader import basket


class Sector(unittest.TestCase):
    def test_rules(self):
        f = basket.sector_of
        self.assertEqual(f('삼성전자', '통신 및 방송 장비 제조업', ''), '반도체')        # 이름으로 직접 지정
        self.assertEqual(f('SK하이닉스', '반도체 제조업', ''), '반도체')
        self.assertEqual(f('에이피알', '기타 화학제품 제조업', '화장품'), '소비재')
        self.assertEqual(f('KB금융', '기타 금융업', '-'), '금융')
        self.assertEqual(f('신한지주', '기타 금융업', '금융지주회사'), '금융')          # 이름에 없으면 사업 내용으로
        self.assertIsNone(f('한국앤컴퍼니', '기타 금융업', '비금융지주회사'))
        self.assertIsNone(f('SK스퀘어', '기타 금융업', '지주회사'))
        self.assertIsNone(f('두산', '전자부품 제조업', ''))                           # 수동 지주사 목록
        self.assertIsNone(f('HMM', '해상 운송업', ''))                                # 12개 업종 밖


def marcap_rows(days, code, name, mcap, amount=2e10, volume=1, market='KOSPI', dept=None):
    return [{'Date': d, 'Code': code, 'Name': name, 'Market': market, 'Dept': dept, 'Amount': amount,
             'Marcap': mcap, 'Volume': volume} for d in days]


class Select(unittest.TestCase):
    def test_filters_and_top3(self):
        days = list(pd.bdate_range('2026-08-03', periods=61))
        rows = []
        for i, (code, name) in enumerate([('000010', 'A반도체'), ('000020', 'B반도체'), ('000030', 'C반도체'),
                                          ('000040', 'D반도체')]):
            rows += marcap_rows(days, code, name, 100 - i)                   # D는 4위라 빠짐
        rows += marcap_rows(days, '000015', 'A반도체우', 500)                 # 우선주 (코드 끝자리)
        rows += marcap_rows(days, '000050', '하나스팩1호', 400)
        rows += marcap_rows(days, '000060', 'E리츠', 400)
        rows += marcap_rows(days, '000070', 'F반도체', 300, amount=5e9)       # 거래대금 부족
        rows += marcap_rows(days[:-30], '000080', 'G반도체', 300)             # 최근 상장이 아니라 최근 자료 없음
        rows += marcap_rows(days[-30:], '000090', 'H반도체', 300)             # 상장 30일
        halted = marcap_rows(days, '000100', 'I반도체', 300)
        halted[-5]['Volume'] = 0                                              # 거래정지 하루
        rows += halted
        df = pd.DataFrame(rows)
        sectors = {c: ('반도체 제조업', '') for c in df['Code'].unique()}
        out = basket.select(df, sectors, days[-1])
        self.assertEqual(list(out['name']), ['A반도체', 'B반도체', 'C반도체'])
        self.assertEqual(list(out['rank']), [1, 2, 3])

    def test_effective_from_skips_weekend_and_holiday(self):
        self.assertEqual(basket.trading_day_after(date(2026, 10, 30), 2), date(2026, 11, 3))
        self.assertEqual(basket.trading_day_after(date(2026, 12, 24), 2), date(2026, 12, 29))   # 12/25 휴장


def quote(code, price, open_, rate, high=None, low=None):
    return {'code': code, 'price': price, 'open': open_, 'rate': rate,
            'high': high if high is not None else open_, 'low': low if low is not None else price}


class V3Pick(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.patch = mock.patch.object(cr, 'DATA', self.tmp)
        self.patch.start()
        s = cr.CloseReversalV3()
        s.log = lambda *_: None
        s.sector = {'A': '반도체', 'B': '반도체', 'C': '반도체', 'X': '건설'}
        s.names = {c: c for c in s.sector}
        s.etf = {'A': 'SOXX', 'B': 'SOXX', 'C': 'SOXX', 'X': ''}
        s.us = {'SOXX': -0.03, 'SPY': -0.01, 'QQQ': -0.02}
        self.s = s

    def tearDown(self):
        self.patch.stop()

    def test_spread_filter_and_log(self):
        s = self.s
        qs = [quote('A', 9000, 10000, -12.0), quote('B', 9700, 10000, -4.0), quote('C', 9900, 10000, -3.0),
              quote('X', 9000, 9000, -5.0, high=9000, low=9000)]               # X: 고가 = 저가, 업종 동료 없음
        cands = [(q['code'], {}, q, 'r') for q in qs if s.should_buy({}, q)]
        kept = [c[0] for c in s.pick(cands)]
        # 후보는 A(-10%), B(-3%). C(-1%), X(0%)는 하락 조건에 안 걸리지만 동료 시세로는 쓰인다
        # A: R -12%, 동료(B,C) 평균 -3.5% → 괴리 -8.5%p 제외. B: -4% - 동료(A,C) 평균 -7.5% = +3.5%p 통과
        self.assertEqual(kept, ['B'])
        d = pd.read_csv(next((self.tmp / s.book / 'decisions').glob('*.csv')), dtype={'code': str})
        a = d.set_index('code').loc['A']
        self.assertEqual((a['passed'], round(a['spread'], 3), a['peers']), (0, -0.085, 'B C'))
        self.assertEqual(a['us_rescue'], 1)                                  # SOXX -3%, 동료 평균 -3.5% → 기록만

    def test_no_peer_and_flat_bar(self):
        s = self.s
        q = quote('X', 9500, 10000, -5.0, high=9500, low=9500)
        kept = s.pick([('X', {}, q, 'r')])
        self.assertEqual(len(kept), 1)
        self.assertIn('업종 비교 불가', kept[0][3])
        d = pd.read_csv(next((self.tmp / s.book / 'decisions').glob('*.csv')))
        self.assertEqual(d.loc[0, 'near_low'], 0.0)                         # 고가 = 저가 → 0
        self.assertEqual(d.loc[0, 'passed'], 1)

    def test_stale_peer_ignored(self):
        s = self.s
        s.seen['B'] = (time.time() - 1000, quote('B', 9000, 10000, -10.0))   # 오래된 시세는 안 씀
        q = quote('A', 9000, 10000, -12.0)
        kept = s.pick([('A', {}, q, 'r')])
        self.assertEqual(len(kept), 1)                                       # 동료 없음 → 통과


class Report(unittest.TestCase):
    def test_unfiltered_replay_and_trade(self):
        d = pd.DataFrame({'time': ['14:30:05'] * 3 + ['14:31:10'] * 3,
                          'code': ['A', 'B', 'C', 'A', 'D', 'E'],
                          'r_open': [-0.05, -0.03, -0.02, -0.05, -0.08, -0.06],
                          'price': [100, 200, 300, 101, 400, 500]})
        self.assertEqual(v3_report.unfiltered_picks(d), [('A', 100), ('B', 200), ('C', 300), ('D', 400)])
        self.assertLess(v3_report.trade(10000, 10000), 0)                    # 같은 가격이면 비용만큼 손해
        self.assertNotEqual(v3_report.trade(10000, float('nan')), v3_report.trade(10000, float('nan')))

    def test_replay_uses_first_passed_price(self):
        d = pd.DataFrame({'code': ['A', 'A', 'B'], 'passed': [0, 1, 1], 'price': [9000, 10000, 20000]})
        self.assertEqual(v3_report.replay(d, ['A'], {'A': 10000}), v3_report.trade(10000, 10000))   # 제외됐던 9000이 아니라 통과한 10000
        self.assertEqual(v3_report.replay(d, [], {}), 0)


if __name__ == '__main__':
    unittest.main()

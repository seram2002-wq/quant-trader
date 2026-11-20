"""장 마감 반전 v2 악재 필터와 분봉 이어 받기 확인

    python -m unittest discover tests
"""
import csv
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

from trader import disclosures
from trader.disclosures import classify, good_news, scan
from trader.kis_client import KISClient
from strategies.close_reversal import CloseReversalV2

FIELDS = ['rcept_no', 'rcept_dt', 'stock_code', 'report_nm', 'collected_at']


class Classify(unittest.TestCase):
    def test_real_titles(self):
        self.assertEqual(classify('[기재정정]주요사항보고서(유상증자결정)')[1], '유상증자결정')
        self.assertEqual(classify('단일판매ㆍ공급계약해지')[1], '공급계약해지')
        self.assertEqual(classify('주요사항보고서(유상증자결정)(자회사의 주요경영사항)'), (None, None))
        self.assertEqual(classify('유상증자결정(종속회사의주요경영사항)'), (None, None))
        self.assertEqual(classify('주권매매거래정지해제              (액면병합 주권 변경상장)'), (None, None))
        self.assertEqual(classify('조회공시요구(풍문또는보도)'), (None, '조회공시요구'))

    def test_good_news_real_titles(self):
        """data/dart에 실제로 나온 제목 (2026-11-16 ~ 20)"""
        good = {
            '단일판매ㆍ공급계약체결': '단일판매공급계약체결',
            '단일판매ㆍ공급계약체결(자율공시)': '단일판매공급계약체결',
            '주요사항보고서(자기주식취득결정)': '자기주식취득결정',
            '주요사항보고서(자기주식취득신탁계약체결결정)': '자기주식취득신탁계약체결결정',
        }
        not_good = ['[기재정정]단일판매ㆍ공급계약체결', '[기재정정]단일판매ㆍ공급계약체결(자율공시)',
                    '[첨부정정]주요사항보고서(자기주식취득결정)', '단일판매ㆍ공급계약해지',
                    '주요사항보고서(자기주식처분결정)', '자기주식취득결과보고서',
                    '주요사항보고서(자기주식취득신탁계약해지결정)', '주권매매거래정지 (단일판매공급계약)',
                    '단일판매ㆍ공급계약체결(자회사의 주요경영사항)', '단일판매ㆍ공급계약체결(종속회사의주요경영사항)']
        self.assertEqual({t: good_news(t) for t in good}, good)
        self.assertEqual([good_news(t) for t in not_good], [None] * len(not_good))


class Window(unittest.TestCase):
    """2026-12-25(금) 성탄절 휴장 → 12-28(월)에는 12-24(목) 저녁 공시를 봐야 한다"""

    def setUp(self):
        tmp = Path(tempfile.mkdtemp())
        self.patches = [mock.patch.object(disclosures, 'DART_DIR', tmp / 'dart'),
                        mock.patch.object(disclosures, 'MINUTE_DIR', tmp / 'minute')]
        for p in self.patches:
            p.start()
        (tmp / 'dart').mkdir()
        (tmp / 'minute' / '20261224').mkdir(parents=True)           # 프로그램이 돈 마지막 거래일
        (tmp / 'minute' / '20261224' / '005930.csv').write_text('x')
        self.now = datetime(2026, 12, 28, 14, 35)

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def write(self, day, rows):
        with open(disclosures.DART_DIR / f'{day}.csv', 'w', newline='', encoding='utf-8-sig') as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            w.writeheader()
            w.writerows(rows)

    def test_holiday_keeps_last_trading_evening(self):
        self.write('20261224', [
            {'rcept_no': '1', 'rcept_dt': '20261224', 'stock_code': '111111',
             'report_nm': '주요사항보고서(유상증자결정)', 'collected_at': '2026-12-24 10:00:00'},   # 장중: 이미 반영
            {'rcept_no': '2', 'rcept_dt': '20261224', 'stock_code': '222222',
             'report_nm': '주요사항보고서(전환사채권발행결정)', 'collected_at': '2026-12-24 18:00:00'}])
        bad, watch = scan({'111111', '222222'}, self.now)
        self.assertEqual(set(bad), {'222222'})
        self.assertEqual(bad['222222'][4], '')                     # 장중 기록이 있으니 주의 문구 없음

    def test_no_intraday_record_adds_note(self):
        self.write('20261224', [
            {'rcept_no': '1', 'rcept_dt': '20261224', 'stock_code': '111111',
             'report_nm': '주요사항보고서(유상증자결정)', 'collected_at': '2026-12-28 08:30:00'}])
        bad, _ = scan({'111111'}, self.now)
        self.assertIn('전날 장중', bad['111111'][4])

    def test_watch_then_bad_is_bad_only(self):
        self.write('20261228', [
            {'rcept_no': '1', 'rcept_dt': '20261228', 'stock_code': '333333',
             'report_nm': '조회공시요구(풍문또는보도)', 'collected_at': '2026-12-28 09:10:00'},
            {'rcept_no': '2', 'rcept_dt': '20261228', 'stock_code': '333333',
             'report_nm': '주요사항보고서(유상증자결정)', 'collected_at': '2026-12-28 14:20:00'}])
        bad, watch = scan({'333333'}, self.now)
        self.assertEqual((set(bad), watch), ({'333333'}, {}))


class PickAlerts(unittest.TestCase):
    def test_exclusion_alert_after_watch_log(self):
        s = CloseReversalV2()
        s.log, s.notify = mock.Mock(), mock.Mock()
        cand = [('333333', {}, {'price': 97, 'open': 100}, '하락')]
        with mock.patch('trader.disclosures.scan', return_value=({}, {'333333': ('조회공시요구', 't')})):
            self.assertEqual(len(s.pick(cand)), 1)
        bad = {'333333': ('자금 조달·희석', '유상증자결정', 't', '2026-12-28 14:40:00', '')}
        with mock.patch('trader.disclosures.scan', return_value=(bad, {})):
            self.assertEqual(s.pick(cand), [])
        s.notify.assert_called_once()                             # 애매 기록이 먼저 있어도 제외 알림은 간다


class MinuteBars(unittest.TestCase):
    def test_keeps_0900_bar_when_batch_starts_at_0901(self):
        today = datetime.now().strftime('%Y%m%d')
        yday = (datetime.now() - timedelta(days=1)).strftime('%Y%m%d')
        start = datetime.strptime('090000', '%H%M%S')
        bars = [(today, (start + timedelta(minutes=i)).strftime('%H%M%S')) for i in range(31)]     # 09:00 ~ 09:30
        bars = [(yday, f'19{m:02d}00') for m in range(31, 60)] + [(yday, '200000')] + bars       # 전날 넥스트레이드

        def fake_get(path, tr_id, params):
            until = params['FID_INPUT_HOUR_1']
            upto = [b for b in bars if b[0] < today or b[1] <= until][-30:]
            return {'output2': [{'stck_bsop_date': d, 'stck_cntg_hour': t, 'stck_prpr': '1'}
                                for d, t in reversed(upto)]}

        c = KISClient.__new__(KISClient)
        c._get = fake_get
        got = c.get_minute_bars('005930', end='093000')       # 첫 묶음이 09:01 ~ 09:30
        self.assertEqual([b['time'] for b in got], [t for _, t in bars[-31:]])


if __name__ == '__main__':
    unittest.main()

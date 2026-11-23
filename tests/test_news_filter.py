"""뉴스 판정 그림자 기록: 규칙, 저장·중복, 조회 주기 (네이버에 실제로 요청하지 않음)

    python -m unittest discover tests
"""
import csv
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import run
from trader import news_filter as nf

SINCE = datetime(2026, 11, 19, 15, 30)
NOW = datetime(2026, 11, 20, 10, 0)
ITEMS = [
    {'title': '<b>에이</b>전자, 압수수색 받아', 'originallink': 'https://a/1', 'pubDate': 'Fri, 20 Nov 2026 09:10:00 +0900'},
    {'title': '<b>에이</b>전자, 1천억 &quot;수주&quot;', 'originallink': 'https://a/2', 'pubDate': 'Thu, 19 Nov 2026 18:00:00 +0900'},
    {'title': '<b>에이</b>전자 횡령 의혹', 'originallink': 'https://a/0', 'pubDate': 'Thu, 19 Nov 2026 11:00:00 +0900'},  # 전날 장중
]


class Judge(unittest.TestCase):
    def test_rules(self):
        cases = {
            '에이전자, 압수수색 받아': ('악재', ['압수수색']),
            '에이전자 횡령 혐의 무혐의 처분': ('예외', ['횡령', '무혐의']),
            '에이전자 거래정지 해제': ('예외', ['거래정지', '해제']),
            '에이전자 역대 최대 실적, 흑자전환': ('호재', ['역대최대', '최대실적', '흑자전환']),
            '에이전자 단일판매 공급계약해지': ('악재', ['계약해지']),          # '공급계약'을 호재로 다시 세지 않음
            '에이전자 수주에도 유상증자': ('혼재', ['유상증자', '수주']),
            '에이전자 주가 보합': ('중립', []),
        }
        self.assertEqual({t: nf.judge(t) for t in cases}, cases)

    def test_clean(self):
        self.assertEqual(nf.clean('<b>에이</b> &quot;수주&quot;'), '에이 "수주"')


class Check(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.status = 200
        for p in (mock.patch.object(nf, 'NEWS_DIR', self.dir),
                  mock.patch.object(nf, 'since_prev_close', return_value=SINCE),
                  mock.patch.object(nf.requests, 'get', side_effect=self.fake_get)):
            p.start()
            self.addCleanup(p.stop)

    def fake_get(self, url, timeout, params, headers):
        assert headers['X-NCP-APIGW-API-KEY-ID'] == 'id' and headers['X-NCP-APIGW-API-KEY'] == 'sec'
        assert url == nf.API_URL and params['sort'] == 'date'
        return mock.Mock(status_code=self.status, text='err', json=lambda: {'items': ITEMS})

    def rows(self):
        with open(self.dir / '20261120.csv', encoding='utf-8-sig') as f:
            return list(csv.DictReader(f))

    def test_saves_new_articles_once(self):
        seen = set()
        self.assertEqual(nf.check({'000001': '에이전자'}, 'id', 'sec', seen, now=NOW), 2)
        rows = self.rows()
        self.assertEqual([(r['verdict'], r['title'], r['link']) for r in rows],
                         [('악재', '에이전자, 압수수색 받아', 'https://a/1'),
                          ('호재', '에이전자, 1천억 "수주"', 'https://a/2')])
        self.assertEqual(list(rows[0]), nf.FIELDS)
        self.assertEqual(rows[1]['pub_time'], '2026-11-19 18:00:00')
        self.assertEqual(nf.check({'000001': '에이전자'}, 'id', 'sec', seen, now=NOW), 0)    # 이미 본 링크
        self.assertEqual(nf.load_seen('20261120'), seen)                                       # 다시 켜도 이어 감

    def test_error_response_writes_nothing(self):
        self.status = 401
        log = mock.Mock()
        self.assertEqual(nf.check({'000001': '에이전자', '000002': '비전자'}, 'id', 'sec', set(), now=NOW, log=log), 0)
        log.assert_called_once()                                                               # 첫 종목에서 멈춤
        self.assertFalse((self.dir / '20261120.csv').exists())


class Schedule(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(run.config, 'NEWS_SHADOW', True)                  # 켠 상태로 시험 (기본은 꺼짐)
        p.start()
        self.addCleanup(p.stop)

    def runner(self, picks=(), positions=None):
        return SimpleNamespace(picks=list(picks), symbols={c: (f'종목{c}', 'stock') for c in picks},
                               broker=SimpleNamespace(positions=positions or {}))

    def test_fast_window_uses_top_picks_every_3_minutes(self):
        nc = run.NewsCheck(client=None)
        r = self.runner([f'00000{i}' for i in range(7)])
        codes = nc.codes([r], datetime(2026, 11, 20, 14, 50))                    # 마감 40분 전
        self.assertEqual(list(codes), [f'00000{i}' for i in range(5)])
        self.assertIsNone(nc.codes([r], datetime(2026, 11, 20, 14, 51)))        # 3분 안 지남

    def test_normal_poll_uses_rank_and_held_stocks_only(self):
        client = mock.Mock(get_trade_value_rank=lambda: [{'code': '111111', 'name': '비전자'},
                                                         {'code': '069500', 'name': 'KODEX 200'}])
        nc = run.NewsCheck(client)
        r = self.runner(positions={'222222': {'name': '씨화학', 'kind': 'stock'},
                                   '114800': {'name': 'KODEX 인버스', 'kind': 'etf'}})
        self.assertEqual(nc.codes([r], datetime(2026, 11, 20, 10, 0)), {'111111': '비전자', '222222': '씨화학'})
        self.assertIsNone(nc.codes([r], datetime(2026, 11, 20, 10, 5)))         # 20분 안 지남

    def test_runs_check_in_thread(self):
        nc = run.NewsCheck(client=None)
        nc.keys = ('id', 'sec')
        with mock.patch.object(nc, 'codes', return_value={'000001': '에이전자'}), \
                mock.patch.object(nf, 'check') as check, mock.patch.object(nf, 'load_seen', return_value=set()):
            nc.run([], now=NOW)
            nc.thread.join(timeout=5)
        check.assert_called_once_with({'000001': '에이전자'}, 'id', 'sec', set(), now=NOW)

    def test_unexpected_error_never_reaches_trading_loop(self):
        nc = run.NewsCheck(client=mock.Mock(get_trade_value_rank=mock.Mock(side_effect=KeyError('x'))))
        nc.keys = ('id', 'sec')
        nc.run([], now=NOW)                                                     # 예외가 나오면 테스트 실패
        self.assertIsNone(nc.thread)

    def test_switch_off_does_nothing_even_with_keys(self):
        nc = run.NewsCheck(client=None)
        nc.keys = ('id', 'sec')
        with mock.patch.object(run.config, 'NEWS_SHADOW', False), mock.patch.object(nc, 'codes') as codes:
            nc.run([])
        codes.assert_not_called()

    def test_no_keys_does_nothing(self):
        nc = run.NewsCheck(client=None)
        nc.keys = ('', '')
        with mock.patch.object(nc, 'codes') as codes:
            nc.run([])
        codes.assert_not_called()


if __name__ == '__main__':
    unittest.main()

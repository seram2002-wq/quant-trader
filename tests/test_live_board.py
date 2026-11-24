"""실시간 잔고판: 처음엔 올리고, 그다음부터는 같은 메시지를 고치는지

    python -m unittest tests.test_live_board
"""
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from trader import live_board
from trader.paper_broker import PaperBroker


class FakeSlack:
    def __init__(self):
        self.posts, self.updates = [], []

    def chat_postMessage(self, channel, text, blocks):
        self.posts.append(text)
        return {'channel': 'C1', 'ts': '111.1'}

    def chat_update(self, channel, ts, text, blocks):
        self.updates.append((channel, ts, text))


class Quotes:
    def get(self, code):
        return {'price': {'069500': 40000, 'A': 1100}[code], 'rate': 1.0}


class Board(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.mkdtemp()
        self.patches = [mock.patch.object(live_board, 'STATE', Path(tmp) / 'live_board.json'),
                        mock.patch('trader.paper_broker.DATA_ROOT', Path(tmp))]
        for p in self.patches:
            p.start()
        b = PaperBroker('t', 10000)
        b.start_day('20261124')
        b.state['cash'] = 9000
        b.positions['A'] = {'qty': 1, 'avg_price': 1000, 'cost': 1000, 'name': '에이'}
        self.runners = [SimpleNamespace(broker=b, note=SimpleNamespace(prefix='[가상·테스트 v1] '))]
        self.slack = FakeSlack()
        self.note = SimpleNamespace(slack=self.slack, channel='#seram-quant')

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def test_message(self):
        text, blocks = live_board.LiveBoard(self.note).message(self.runners, Quotes(), datetime(2026, 11, 24, 14, 42))
        self.assertEqual(text, '실시간 잔고 14:42 갱신 · 오늘 합계 +100원')
        self.assertEqual(blocks[-1]['fields'][0]['text'],
                         '*가상·테스트 v1*\n10,100원  🟢 +100\n에이 +10.0%')   # 매입가 1,000 → 1,100

    def test_post_then_update_and_resume(self):
        board = live_board.LiveBoard(self.note)
        board.run(self.runners, Quotes())
        board.run(self.runners, Quotes())                      # 1분 안 → 아무것도 안 함
        board.run(self.runners, Quotes(), final=True)          # 마감은 바로
        self.assertEqual(len(self.slack.posts), 1)
        self.assertEqual(self.slack.updates[0][:2], ('C1', '111.1'))
        self.assertIn('마감', self.slack.updates[0][2])
        again = live_board.LiveBoard(self.note)                # run.py를 다시 켜도 같은 메시지
        self.assertEqual(again.ts, '111.1')


if __name__ == '__main__':
    unittest.main()

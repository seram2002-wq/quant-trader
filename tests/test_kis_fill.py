"""체결가 조회: 모의 서버가 주문별 목록을 비워 보낼 때 종목·방향 합계로 대신하는지

    python -m unittest tests.test_kis_fill
"""
import unittest

from trader.kis_client import KISClient, KISError


def client(responses):
    c = KISClient.__new__(KISClient)                   # .env 없이 (네트워크 안 씀)
    c._account = ('12345678', '01')
    c.calls = []

    def fake_get(path, tr_id, params):
        c.calls.append(params['SLL_BUY_DVSN_CD'])
        r = responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r
    c._get = fake_get
    return c


EMPTY = {'output1': [], 'output2': {'tot_ccld_qty': '142', 'tot_ccld_amt': '13882300'}}


class GetFill(unittest.TestCase):
    def test_uses_order_row_when_present(self):
        c = client([{'output1': [{'odno': '0000123', 'tot_ccld_qty': '10', 'tot_ccld_amt': '1005000'}]}])
        self.assertEqual(c.get_fill('123', '005930', 'sell'), {'qty': 10, 'avg_price': 100500.0})
        self.assertEqual(c.calls, ['00'])

    def test_falls_back_to_side_total(self):
        c = client([EMPTY, {'output1': [], 'output2': {'tot_ccld_qty': '13', 'tot_ccld_amt': '2300700'}}])
        self.assertEqual(c.get_fill('123', '018260', 'sell'), {'qty': 13, 'avg_price': 2300700 / 13})
        self.assertEqual(c.calls, ['00', '01'])                     # 매도 = 01
        c = client([EMPTY, {'output1': [], 'output2': [{'tot_ccld_qty': '43', 'tot_ccld_amt': '2347850'}]}])
        self.assertEqual(c.get_fill('123', '028050', 'buy')['qty'], 43)
        self.assertEqual(c.calls, ['00', '02'])                     # 매수 = 02

    def test_none_when_unknown(self):
        self.assertIsNone(client([EMPTY]).get_fill('123', '018260'))   # 방향을 모르면 합계를 쓰지 않음
        self.assertIsNone(client([EMPTY, {'output2': {'tot_ccld_qty': '0'}}]).get_fill('1', '018260', 'sell'))
        self.assertIsNone(client([KISError('x')]).get_fill('1', '018260', 'sell'))


if __name__ == '__main__':
    unittest.main()

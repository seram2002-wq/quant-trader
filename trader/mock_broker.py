"""모의투자 계좌 브로커

가상 장부(PaperBroker)와 같은 방식으로 쓰지만, 사고팔 때 모의투자 계좌에 실제로
주문한다. 체결 수량과 체결가는 계좌에서 확인한 값을 쓴다.

- 매수: 최유리지정가로 주문 → 2초 간격으로 체결 확인 → 덜 체결되면 잔량 취소
- 매도: 시장가 주문 → 체결 확인
- 체결가: 주문 체결 조회 값, 조회가 안 되면 매수는 잔고의 평균 매입가, 매도는 주문 직전 현재가
- 손익: 체결가 기준으로 계산하고, 수수료와 세금은 config의 값으로 추정
  (모의투자 계좌가 실제로 떼는 비용과는 다를 수 있음)
- 장부의 현금은 전략에 배정한 자금(capital) 기준으로 따로 관리한다.
  계좌에 그보다 많은 돈이 있어도 전략은 배정된 자금만 쓴다.

이 계좌는 이 전략 전용으로 쓴다. 홈페이지에서 직접 주문하거나 다른 프로그램이
같은 계좌로 주문하면 장부와 계좌가 어긋난다.
"""
import time
from datetime import datetime

import config
from trader.kis_client import KISError, OrderUncertain
from trader.paper_broker import PaperBroker

CHECK_TRIES = 3         # 주문 뒤 체결 확인 횟수
CHECK_GAP = 2           # 확인 간격(초)


class MockBroker(PaperBroker):
    account = 'mock'

    def __init__(self, book, capital, version, client, note):
        super().__init__(book, capital, version)
        self.client = client
        self.note = note

    def _held(self, code):
        return self.client.get_balance().get(code)

    # ------------------------------------------------------------ 하루 시작
    def start_day(self, today):
        super().start_day(today)
        held = self.client.get_balance()
        for code in list(self.positions):              # 장부에는 있는데 계좌에는 없는 종목
            if code not in held:
                p = self.positions.pop(code)
                self.note.send(f'주의 : 장부의 {p.get("name", code)}({code}) {p["qty"]:,}주가 '
                               f'계좌에 없어 장부에서 지웠습니다. 체결 내역을 확인하세요.')
        self._save()
        others = [f'{v["name"]}({c}) {v["qty"]:,}주' for c, v in held.items()
                  if c not in self.positions]
        if others:
            self.note.send('주의 : 이 전략이 사지 않은 종목이 계좌에 있습니다 (건드리지 않음) : '
                           + ', '.join(others))

    # ------------------------------------------------------------ 매수
    def buy(self, code, name, kind, price, budget, reason=''):
        before = (self._held(code) or {}).get('qty', 0)
        account_cash = self.client.get_buyable_cash(code)
        money = min(budget, self.cash, account_cash)
        qty = int(money // (price * (1 + config.SLIPPAGE) * (1 + config.FEE_RATE)))
        if qty <= 0:
            return 0
        order = None
        try:
            order = self.client.order('buy', code, qty, best=True)   # 최유리지정가
        except OrderUncertain as ex:
            self.note.send(f'주의 : {name}({code}) 매수 주문 응답 없음, 잔고로 확인합니다 ({ex})')
        held_qty = before
        for _ in range(CHECK_TRIES):
            time.sleep(CHECK_GAP)
            held_qty = (self._held(code) or {}).get('qty', 0)
            if held_qty - before >= qty:
                break
        if held_qty - before < qty and order and order.get('order_no'):
            try:
                self.client.cancel(order)                # 미체결 잔량 취소
            except KISError:
                pass                                     # 이미 다 체결됐으면 취소할 것이 없다
            time.sleep(CHECK_GAP)
            held_qty = (self._held(code) or {}).get('qty', 0)
        filled = held_qty - before
        if filled <= 0:
            self.note.send(f'매수 미체결 : {name}({code}) {qty:,}주 주문이 체결되지 않았습니다.')
            self.state['today'].setdefault('traded', []).append(code)
            self._save()
            return 0

        fill = self.client.get_fill(order['order_no'], code, 'buy') if order else None
        avg = fill['avg_price'] if fill and fill['qty'] else \
            (self._held(code) or {}).get('avg_price') or price
        amount = round(avg * filled)
        fee = round(amount * config.FEE_RATE)
        self.state['cash'] -= amount + fee
        self.positions[code] = {
            'qty': filled, 'avg_price': round(avg, 2), 'cost': amount + fee,
            'high': price, 'name': name, 'kind': kind,
            'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'order_no': order['order_no'] if order else '',
        }
        self.state['today'].setdefault('traded', []).append(code)
        self._save()
        note = '' if filled == qty else f' (주문 {qty:,}주 중 일부 체결, 나머지 취소)'
        self._record({'time': self.positions[code]['time'], 'side': 'BUY', 'code': code,
                      'name': name, 'qty': filled, 'price': round(avg, 2), 'amount': amount,
                      'fee': fee, 'tax': 0, 'profit': '', 'reason': reason + note})
        return filled

    # ------------------------------------------------------------ 매도
    def sell(self, code, price, reason=''):
        p = self.positions[code]
        held = self._held(code)
        if not held:                                     # 이미 팔렸거나 계좌에 없음
            self.positions.pop(code)
            self._save()
            raise KISError(f'{p.get("name", code)}({code})이 계좌에 없어 장부에서 지웠습니다.')
        qty = min(p['qty'], held['sellable'])
        if qty <= 0:
            raise KISError(f'{p.get("name", code)}({code}) 매도 가능 수량이 없습니다.')
        order = None
        try:
            order = self.client.order('sell', code, qty)  # 시장가
        except OrderUncertain as ex:
            self.note.send(f'주의 : {p.get("name", code)}({code}) 매도 주문 응답 없음, '
                           f'잔고로 확인합니다 ({ex})')
        remain = held['qty']
        for _ in range(CHECK_TRIES):
            time.sleep(CHECK_GAP)
            remain = (self._held(code) or {}).get('qty', 0)
            if remain <= held['qty'] - qty:
                break
        sold = held['qty'] - remain
        if sold <= 0:
            raise KISError(f'{p.get("name", code)}({code}) 매도가 아직 체결되지 않았습니다. '
                           f'다음 확인 때 다시 시도합니다.')

        fill = self.client.get_fill(order['order_no'], code, 'sell') if order else None
        avg = fill['avg_price'] if fill and fill['qty'] else price
        amount = round(avg * sold)
        fee = round(amount * config.FEE_RATE)
        tax = round(amount * config.STOCK_SELL_TAX) if p.get('kind', 'stock') == 'stock' else 0
        cost = p['cost'] * sold / p['qty']
        profit = round(amount - fee - tax - cost)
        self.state['cash'] += amount - fee - tax
        if sold >= p['qty']:
            self.positions.pop(code)
        else:                                            # 일부만 팔림: 남은 수량은 다음에 다시 판다
            p['qty'] -= sold
            p['cost'] -= cost
        today = self.state['today']
        today['realized'] = today.get('realized', 0) + profit
        today['wins' if profit > 0 else 'losses'] = \
            today.get('wins' if profit > 0 else 'losses', 0) + 1
        self._save()
        self._record({'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 'side': 'SELL',
                      'code': code, 'name': p.get('name', code), 'qty': sold,
                      'price': round(avg, 2), 'amount': amount, 'fee': fee, 'tax': tax,
                      'profit': profit,
                      'reason': reason + ('' if fill else ' (체결가는 주문 직전 현재가로 추정)')})
        result = dict(p, qty=sold, cost=cost)
        return profit, result

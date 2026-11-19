"""가상 장부 (페이퍼 브로커)

모의투자 계좌에 연결한 전략은 mock_broker.MockBroker가 이 클래스를 이어받아
주문과 체결 부분만 실제 계좌로 바꾼다.

실제 계좌에 주문하지 않고, 가상 현금과 보유 종목을 직접 관리한다.
상태는 data/state.json에, 매매 기록은 data/trades.csv에 저장해서
프로그램을 껐다 켜도 이어진다.

체결 가격은 신호가 난 순간의 현재가에 SLIPPAGE만큼 불리하게 잡고,
수수료(FEE_RATE)와 일반 주식 매도 세금(STOCK_SELL_TAX)을 뺀다.
호가 물량, 일부 체결 같은 상황은 재현하지 않으므로 실제보다 결과가 조금 좋게 나온다.
"""
import csv
import json
import os
from datetime import datetime
from pathlib import Path

import config

DATA_ROOT = Path(__file__).resolve().parent.parent / 'data'
TRADE_FIELDS = ['time', 'side', 'code', 'name', 'qty', 'price', 'amount',
                'fee', 'tax', 'profit', 'reason', 'version']


class PaperBroker:
    account = 'paper'

    def __init__(self, book, capital, version='', slippage=None):
        """book: 장부 이름 (data/<book>/에 저장), capital: 전략이 쓰는 자금, version: 전략 버전
        slippage: 가상 체결 가격 차이. 없으면 config.SLIPPAGE (호가가 촘촘한 ETF는 작게 줄 수 있음)"""
        self.book, self.capital, self.version = book, capital, version
        self.slip = config.SLIPPAGE if slippage is None else slippage
        data_dir = DATA_ROOT / book
        data_dir.mkdir(parents=True, exist_ok=True)
        self.state_file = data_dir / 'state.json'
        self.trades_file = data_dir / 'trades.csv'
        if self.state_file.exists():
            self.state = json.loads(self.state_file.read_text(encoding='utf-8'))
        else:
            self.state = {'cash': capital, 'positions': {},
                          'date': '', 'today': {}}

    # ------------------------------------------------------------ 저장
    def _save(self):
        tmp = self.state_file.with_suffix('.tmp')
        tmp.write_text(json.dumps(self.state, ensure_ascii=False, indent=2),
                       encoding='utf-8')
        os.replace(tmp, self.state_file)            # 저장 중에 꺼져도 파일이 깨지지 않게

    def _record(self, row):
        new = not self.trades_file.exists()
        with open(self.trades_file, 'a', newline='', encoding='utf-8-sig') as f:
            w = csv.DictWriter(f, fieldnames=TRADE_FIELDS)
            if new:
                w.writeheader()
            w.writerow({**row, 'version': self.version})

    # ------------------------------------------------------------ 하루 시작
    def start_day(self, today):
        """날짜가 바뀌었으면 오늘의 기록을 새로 시작한다."""
        if self.state['date'] != today:
            self.state['date'] = today
            self.state['today'] = {'traded': [], 'realized': 0, 'wins': 0,
                                   'losses': 0,
                                   'start_equity': self.state['cash'] + sum(
                                       p['qty'] * p['avg_price']
                                       for p in self.state['positions'].values())}
            self._save()

    # ------------------------------------------------------------ 조회
    @property
    def cash(self):
        return self.state['cash']

    @property
    def positions(self):
        return self.state['positions']

    def flag_today(self, key):
        """오늘 한 번만 하는 일(종목 교체 등)을 했는지"""
        return bool(self.state['today'].get(key))

    def set_flag_today(self, key):
        self.state['today'][key] = True
        self._save()

    def traded_today(self, code):
        return code in self.state['today'].get('traded', [])

    def equity(self, prices):
        """총자산 = 현금 + 보유 종목 평가금액 (prices: {code: 현재가})"""
        return self.cash + sum(p['qty'] * prices.get(code, p['avg_price'])
                               for code, p in self.positions.items())

    # ------------------------------------------------------------ 가상 체결
    def buy(self, code, name, kind, price, budget, reason=''):
        """budget 안에서 살 수 있는 만큼 가상 매수. 체결 수량을 돌려준다.

        kind: 'etf' 또는 'stock' (매도 세금 계산용)
        """
        fill = price * (1 + self.slip)
        qty = int(min(budget, self.cash) // (fill * (1 + config.FEE_RATE)))
        if qty <= 0:
            return 0
        amount = round(fill * qty)
        fee = round(amount * config.FEE_RATE)
        self.state['cash'] -= amount + fee
        self.positions[code] = {
            'qty': qty, 'avg_price': round(fill, 2),
            'cost': amount + fee,                 # 수수료까지 포함한 매수 금액
            'high': price,                        # 매수 후 최고가 (전략에서 사용)
            'name': name, 'kind': kind,
            'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        }
        self.state['today'].setdefault('traded', []).append(code)
        self._save()
        self._record({'time': self.positions[code]['time'], 'side': 'BUY',
                      'code': code, 'name': name, 'qty': qty,
                      'price': round(fill, 2), 'amount': amount, 'fee': fee,
                      'tax': 0, 'profit': '', 'reason': reason})
        return qty

    def sell(self, code, price, reason=''):
        """보유 수량 전부 가상 매도. 실현 손익(원)을 돌려준다."""
        p = self.positions.pop(code)
        name, kind = p.get('name', code), p.get('kind', 'stock')
        fill = price * (1 - self.slip)
        amount = round(fill * p['qty'])
        fee = round(amount * config.FEE_RATE)
        tax = round(amount * config.STOCK_SELL_TAX) if kind == 'stock' else 0
        proceeds = amount - fee - tax
        profit = proceeds - p['cost']
        self.state['cash'] += proceeds
        today = self.state['today']
        today['realized'] = today.get('realized', 0) + profit
        today['wins' if profit > 0 else 'losses'] = \
            today.get('wins' if profit > 0 else 'losses', 0) + 1
        self._save()
        self._record({'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                      'side': 'SELL', 'code': code, 'name': name,
                      'qty': p['qty'], 'price': round(fill, 2),
                      'amount': amount, 'fee': fee, 'tax': tax,
                      'profit': profit, 'reason': reason})
        return profit, p

    def update_high(self, code, price):
        """보유 종목의 매수 후 최고가를 갱신한다."""
        p = self.positions.get(code)
        if p and price > p['high']:
            p['high'] = price
            self._save()

    # ------------------------------------------------------------ 보고
    def summary(self, prices):
        """현재 가상 잔고와 오늘 성과를 문자열로"""
        eq = self.equity(prices)
        t = self.state['today']
        title = '가상 잔고' if self.account == 'paper' else '전략 잔고'
        lines = [f'{title} : 총자산 {eq:,.0f}원 (현금 {self.cash:,.0f}원), '
                 f'처음 대비 {eq - self.capital:+,.0f}원']
        for code, p in self.positions.items():
            name = p.get('name', code)
            now = prices.get(code, p['avg_price'])
            pnl = now * p['qty'] - p['cost']
            lines.append(f'  {name}({code}) {p["qty"]:,}주, 매입가 {p["avg_price"]:,.0f}, '
                         f'현재가 {now:,}, 평가손익 {pnl:+,.0f}원')
        n = t.get('wins', 0) + t.get('losses', 0)
        lines.append(f'오늘 : 실현손익 {t.get("realized", 0):+,.0f}원, 매도 {n}건'
                     + (f' (이익 {t.get("wins", 0)}, 손실 {t.get("losses", 0)})' if n else ''))
        return '\n'.join(lines)

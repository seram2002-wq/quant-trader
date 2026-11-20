"""매매 실행기: 여러 전략을 동시에 돌린다

    python run.py           장중 실행 (09:05~15:15, 15:20 종료)
    python run.py --check   지금 시점의 전략별 판단만 출력 (주문, 가상 매매 모두 안 함)

전략 목록과 계좌(모의투자/가상) 설정은 config.py의 STRATEGIES에 있다.
전략마다 장부, 슬랙 채널, 메시지 앞머리가 따로다.
"""
import sys
import time
import socket
import importlib
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / '.env', override=True)        # 이 폴더의 .env만 읽는다

import config                                     # noqa: E402
from trader.kis_client import KISClient, KISError  # noqa: E402
from trader.paper_broker import PaperBroker      # noqa: E402
from trader.mock_broker import MockBroker        # noqa: E402
from trader.notifier import Notifier             # noqa: E402
from trader import market                        # noqa: E402

LOCK_PORT = 47285       # 중복 실행 방지용
ACCOUNT_LABEL = {'mock': '모의', 'paper': '가상'}
UNIVERSE_CACHE = {}     # 같은 전략(모의투자, 그림자, 다른 버전)은 감시 종목 목록을 같이 쓴다 {universe_key: (시각, 목록, 설명)}


def hhmm(t):
    return t.hour * 100 + t.minute


def fmt(t):
    return f'{t // 100}:{t % 100:02d}'


class Quotes:
    """현재가 조회. 같은 종목은 QUOTE_TTL초 안에 다시 조회하지 않고 여러 전략이 같이 쓴다."""

    def __init__(self, client):
        self.client = client
        self.cache = {}

    def get(self, code):
        hit = self.cache.get(code)
        if hit and time.time() - hit[0] < config.QUOTE_TTL:
            return hit[1]
        quote = self.client.get_price(code)
        self.cache[code] = (time.time(), quote)
        return quote


class Runner:
    """전략 하나를 돌리는 단위 (전략 + 장부 + 알림)"""

    def __init__(self, spec, client, quotes):
        module_name, class_name = spec['strategy'].rsplit('.', 1)
        self.strategy = getattr(importlib.import_module('strategies.' + module_name), class_name)()
        self.spec = spec
        self.client, self.quotes = client, quotes
        account = spec['account']
        label = f'{ACCOUNT_LABEL[account]}·{self.strategy.name} {self.strategy.VERSION}'
        self.note = Notifier(spec['channel'], label)
        self.strategy.log = self.note.log               # 전략 안의 진행 상황도 같은 로그에
        self.strategy.notify = self.note.send           # 전략이 슬랙에 직접 알릴 때 (예: 악재 공시로 제외)
        book = spec.get('book') or f'{account}_{module_name}'   # 같은 파일의 두 버전을 동시에 돌릴 때 'book'으로 구분
        if account == 'mock':
            self.broker = MockBroker(book, spec['capital'], self.strategy.VERSION, client, self.note)
        else:
            self.broker = PaperBroker(book, spec['capital'], self.strategy.VERSION, spec.get('slippage'))
        self.infos, self.no_data = {}, set()
        self.symbols, self.universe_time = {}, 0.0
        self.prices = {}
        self.budget = 0
        self.reported_hour = None
        self.done = False
        self.last_error = ''

    # ------------------------------------------------------------ 준비
    def start(self):
        self.broker.start_day(datetime.now().strftime('%Y%m%d'))
        equity = self.broker.equity({})
        self.budget = int(self.spec['capital'] * self.spec['budget'])
        s = self.strategy
        start, end = (market.at(x) for x in s.buy_window)
        if s.morning_exit is not None:
            plan = f'매수 {fmt(start)}~{fmt(end)}, 다음 날 {fmt(market.at(s.morning_exit))} 매도'
        elif s.rebalance_time is not None:
            plan = f'{fmt(market.at(s.rebalance_time))} 종목 교체'
        else:
            plan = f'매수 판단 {fmt(start)}~{fmt(end)}'
        if s.morning_exit is None:
            plan += ', 다음 날까지 보유' if s.hold_overnight else f', {fmt(market.at(config.EXIT_TIME))} 일괄 매도'
        open_, close = market.hours()
        if (open_, close) != config.MARKET_HOURS:
            plan += f' (오늘 장 시간 {fmt(open_)}~{fmt(close)})'
        self.note.log('슬랙 알림 : ' + self.note.status())
        self.note.send(f'시작 : {plan}\n'
                       f'자금 {self.spec["capital"]:,}원 (현재 {equity:,.0f}원), '
                       f'종목당 {self.budget:,}원, 최대 {self.spec["max_positions"]}종목, '
                       f'보유 {len(self.broker.positions)}종목')

    def refresh_universe(self):
        if self.symbols and time.time() - self.universe_time < config.UNIVERSE_REFRESH:
            return
        self.universe_time = time.time()
        key = self.strategy.universe_key or type(self.strategy).__name__
        cached = UNIVERSE_CACHE.get(key)
        if cached and time.time() - cached[0] < config.UNIVERSE_REFRESH:
            symbols, source = cached[1], cached[2]
        else:
            try:
                symbols, source = self.strategy.universe(self.client)
                UNIVERSE_CACHE[key] = (time.time(), symbols, source)
            except Exception as ex:
                if self.symbols:
                    self.note.log(f'감시 종목 갱신 실패, 이전 목록 유지 ({ex})')
                    return
                raise
        if symbols and symbols != self.symbols:
            self.symbols = symbols
            names = [n for n, _ in symbols.values()]
            self.note.log(f'감시 종목 {len(names)}개 ({source}) : '
                          + ', '.join(names[:10]) + (' ...' if len(names) > 10 else ''))

    def info(self, code, name):
        if code not in self.infos:
            info = self.strategy.prepare(self.client, code, datetime.now().strftime('%Y%m%d'))
            if info is None:
                if code not in self.no_data:
                    self.no_data.add(code)
                    self.note.log(f'{name}({code}) : 오늘 시세가 아직 없습니다.')
                return None
            self.infos[code] = info
            desc = self.strategy.describe(info)
            if desc:
                self.note.log(f'{name}({code}) : {desc}')
        return self.infos[code]

    # ------------------------------------------------------------ 한 바퀴
    def step(self, now):
        t, s = hhmm(now), self.strategy
        start, end = (market.at(x) for x in s.buy_window)
        if s.morning_exit is not None and t >= market.at(s.morning_exit):
            self.morning_sell(now)
        if t >= market.at(config.EXIT_TIME if s.exit_time is None else s.exit_time):
            self.close_day()
            return
        if t < market.at(config.START_TIME):
            return
        in_window = start <= t < end

        # 보유 종목: 장중 매도 조건이 있는 전략만 계속 확인
        if self.strategy.intraday_exit:
            for code in list(self.broker.positions):
                p = self.broker.positions[code]
                info = self.info(code, p.get('name', code)) or {}
                quote = self.quotes.get(code)
                self.prices[code] = quote['price']
                self.broker.update_high(code, quote['price'])
                reason = self.strategy.should_sell(info, p, quote)
                if reason:
                    self.sell(code, quote['price'], reason)

        # 종목 교체 전략: 하루 한 번 정해진 시각에
        if s.rebalance_time is not None:
            if (market.at(s.rebalance_time) <= t < market.at(config.EXIT_TIME)
                    and not self.broker.flag_today('rebalanced')):
                self.rebalance()

        # 매수 판단
        slots = self.spec['max_positions'] - len(self.broker.positions)
        if in_window and slots > 0 and s.rebalance_time is None:
            self.refresh_universe()
            candidates = []
            for code, (name, kind) in self.symbols.items():
                if code in self.broker.positions:
                    continue
                if not self.strategy.allow_reentry and self.broker.traded_today(code):
                    continue
                info = self.info(code, name)
                if info is None:
                    continue
                quote = self.quotes.get(code)
                self.prices[code] = quote['price']
                reason = self.strategy.should_buy(info, quote)
                if reason:
                    candidates.append((code, info, quote, reason))
            for code, info, quote, reason in self.strategy.pick(candidates)[:slots]:
                name, kind = self.symbols[code]
                qty = self.broker.buy(code, name, kind, quote['price'], self.budget, reason)
                if qty:
                    p = self.broker.positions[code]
                    self.note.send(f'매수 : {name}({code}) {qty:,}주, 체결가 {p["avg_price"]:,.0f}원 - {reason}')

        # 매시 잔고 알림
        if (self.broker.positions and now.minute >= config.REPORT_MINUTE
                and self.reported_hour != now.hour):
            self.reported_hour = now.hour
            for code in self.broker.positions:
                self.prices[code] = self.quotes.get(code)['price']
            self.note.send(self.broker.summary(self.prices))

    def sell(self, code, price, reason):
        name = self.broker.positions[code].get('name', code)
        profit, p = self.broker.sell(code, price, reason)
        rate = profit / p['cost'] * 100 if p['cost'] else 0
        self.note.send(f'매도 : {name}({code}) {p["qty"]:,}주, 매입가 {p["avg_price"]:,.0f} '
                       f'→ 약 {price:,}원, 손익 {profit:+,}원 ({rate:+.2f}%) - {reason}')

    def morning_sell(self, now):
        """전날(또는 그 전에) 산 종목을 판다. 오늘 산 종목은 그대로 둔다"""
        today = now.strftime('%Y-%m-%d')
        for code in list(self.broker.positions):
            p = self.broker.positions[code]
            if p.get('time', '')[:10] < today:
                quote = self.quotes.get(code)
                self.prices[code] = quote['price']
                self.sell(code, quote['price'], f'다음 날 {fmt(market.at(self.strategy.morning_exit))} 매도')

    def rebalance(self):
        """목표 종목에 없는 보유 종목은 팔고, 새 종목은 산다. 오늘 한 번만"""
        targets, report = self.strategy.targets(self.client, dict(self.broker.positions),
                                                self.spec['max_positions'])
        keep = {x['code'] for x in targets}
        for code in list(self.broker.positions):
            if code not in keep:
                quote = self.quotes.get(code)
                self.prices[code] = quote['price']
                self.sell(code, quote['price'], '순위 밖으로 밀림')
        for x in targets:
            if x['code'] in self.broker.positions:
                continue
            if len(self.broker.positions) >= self.spec['max_positions']:
                break
            quote = self.quotes.get(x['code'])
            self.prices[x['code']] = quote['price']
            qty = self.broker.buy(x['code'], x['name'], x['kind'], quote['price'], self.budget, x['reason'])
            if qty:
                p = self.broker.positions[x['code']]
                self.note.send(f'매수 : {x["name"]}({x["code"]}) {qty:,}주, '
                               f'체결가 {p["avg_price"]:,.0f}원 - {x["reason"]}')
        self.broker.set_flag_today('rebalanced')
        self.note.send(report)

    def close_day(self):
        """일괄 매도. 다 팔리면 정리 알림 후 done (다음 날까지 보유하는 전략은 팔지 않음)"""
        if self.strategy.hold_overnight:
            if not self.done:
                self.done = True
                for code in self.broker.positions:
                    self.prices[code] = self.quotes.get(code)['price']
                self.note.send('장 마감 정리 (다음 날까지 보유)\n' + self.broker.summary(self.prices))
            return
        for code in list(self.broker.positions):
            quote = self.quotes.get(code)
            self.prices[code] = quote['price']
            self.sell(code, quote['price'], f'{fmt(market.at(config.EXIT_TIME))} 일괄 매도')
        if not self.broker.positions and not self.done:
            self.done = True
            self.note.send('장 마감 정리\n' + self.broker.summary(self.prices))

    def check(self):
        """지금 시점의 판단만 출력"""
        print(f'\n== {self.note.prefix.strip()} ({self.spec["account"]}) ==')
        if self.strategy.rebalance_time is not None:
            targets, report = self.strategy.targets(self.client, dict(self.broker.positions),
                                                    self.spec['max_positions'])
            print(report)
            print('들고 갈 종목 : ' + (', '.join(x['name'] for x in targets) or '없음'))
            return
        self.refresh_universe()
        for code, (name, kind) in self.symbols.items():
            info = self.info(code, name)
            if info is None:
                print(f'{name}({code}) : 오늘 시세 없음')
                continue
            quote = self.quotes.get(code)
            reason = self.strategy.should_buy(info, quote)
            extra = f', VWAP {quote["vwap"]:,.0f}' if quote.get('vwap') else ''
            print(f'{name}({code}) : 현재가 {quote["price"]:,}, 시가 {quote["open"]:,}{extra}'
                  f'  →  {"매수 신호: " + reason if reason else "대기"}')


def main():
    client = KISClient()
    quotes = Quotes(client)
    # 가상 장부를 먼저 돌린다: 가상은 바로 체결되고, 모의투자는 주문·체결 확인에 시간이 걸려서
    # 그림자 장부가 모의투자와 같은 시점의 시세로 판단하게 하려는 것
    specs = sorted(config.STRATEGIES, key=lambda s: s['account'] != 'paper')
    runners = [Runner(spec, client, quotes) for spec in specs]

    if '--check' in sys.argv:
        for r in runners:
            try:
                r.check()
            except KISError as ex:
                print('실패 :', ex)
        return

    lock = socket.socket()                          # 같은 프로그램이 두 개 돌지 않게
    try:
        lock.bind(('127.0.0.1', LOCK_PORT))
    except OSError:
        print('이미 실행 중입니다. 이 창은 종료합니다.')
        return

    for r in runners:
        for attempt in range(1, 6):                 # 시작 준비 실패 시 30초 간격으로 재시도
            try:
                r.start()
                break
            except (KISError, OSError) as ex:
                if attempt == 5:                    # 이 전략만 빼고 나머지는 계속 돈다
                    r.done = True
                    r.note.send(f'시작 실패, 오늘은 이 전략을 돌리지 않습니다 : {ex}')
                    break
                r.note.log(f'시작 준비 실패 ({attempt}/5) : {ex} → 30초 뒤 다시 시도')
                time.sleep(30)

    dart_check = DartCheck()
    dart_check.run(recent=True)                     # 어제 저녁 공시까지 채우기

    while True:
        now = datetime.now()
        if now.weekday() >= 5:
            print('주말에는 실행하지 않습니다.')
            return
        dart_check.run()                            # 10분마다 (v2 매수 시간에는 1분마다) 오늘 새 공시
        for r in runners:
            if r.done:
                continue
            try:
                r.step(now)
                if r.last_error:
                    r.note.send('오류에서 복구되어 계속 진행합니다.')
                r.last_error = ''
            except (KISError, OSError) as ex:       # 한 전략의 오류가 다른 전략을 멈추지 않게
                if str(ex) != r.last_error:
                    r.last_error = str(ex)
                    r.note.send(f'오류 : {ex}')
        if all(r.done for r in runners) or hhmm(datetime.now()) >= market.at(config.STOP_TIME):
            for r in runners:
                if not r.done and r.broker.positions and not r.strategy.hold_overnight:
                    r.note.send('주의 : 종료 시각까지 팔지 못한 종목이 있습니다. 직접 확인하세요.')
                r.note.send('종료합니다.')
            collect_minute_after_close(client, runners)
            return
        time.sleep(config.LOOP_SLEEP)


class DartCheck:
    """DART 공시를 장중에 주기적으로 저장 (처음 본 시각이 실제 공시 시각에 가깝도록). 실패해도 매매에 영향 없음

    전략 실행 전에 한 번 돌아서, 같은 바퀴의 모든 전략이 같은 공시 목록으로 판단한다.
    """
    EVERY = 600                                     # 초
    FAST = 60                                       # 장 마감 반전 v2 매수 시간(평소 14:30 ~ 15:00)에는 1분마다

    def __init__(self):
        self.last = 0.0

    def run(self, recent=False):
        from strategies.close_reversal import CloseReversalV2
        lo, hi = (market.at(x) for x in CloseReversalV2.buy_window)
        every = self.FAST if lo <= hhmm(datetime.now()) < hi else self.EVERY
        if not recent and time.time() - self.last < every:
            return
        self.last = time.time()
        try:
            from tools.collect_dart import collect_dart, collect_recent
            collect_recent() if recent else collect_dart(quiet=True, full=False)
        except Exception as ex:
            print('DART 공시 저장 실패 :', ex)


def collect_minute_after_close(client, runners):
    """장 마감 1분 뒤 오늘 1분봉과 DART 공시를 저장한다. 당일 분봉은 그날만 받을 수 있어서 매일 쌓아 둔다

    마감 30분 뒤보다 늦게 끝났으면(프로그램을 늦게 켠 날 등) 건너뛴다. 그때는 tools/collect_minute.py를 직접 실행.
    """
    from tools.collect_minute import collect, default_codes
    from tools.collect_dart import collect_dart
    now, close = datetime.now(), market.hours()[1]
    if hhmm(now) >= market.shift(close, 30):
        return
    t = market.shift(close, 1)
    wait = (now.replace(hour=t // 100, minute=t % 100, second=0) - now).total_seconds()
    if wait > 0:
        print(f'{fmt(t)}까지 기다렸다가 오늘 분봉·공시를 저장합니다 ({wait / 60:.0f}분)')
        time.sleep(wait)
    held = {c for r in runners for c in r.broker.positions}
    try:
        collect(client, default_codes(client, held))
    except Exception as ex:                         # 분봉 저장 실패가 매매 기록에 영향 주지 않게
        print('분봉 저장 실패 :', ex)
    try:
        collect_dart()
    except Exception as ex:
        print('DART 공시 저장 실패 :', ex)


if __name__ == '__main__':
    try:
        main()
    except KISError as e:
        print('시작 실패 :', e)
        sys.exit(1)
    except KeyboardInterrupt:
        print('사용자가 중단했습니다. 장부(data/)는 그대로 남고, 모의투자 계좌의 보유 종목은 직접 확인하세요.')

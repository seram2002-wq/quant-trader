"""장 마감 반전 전략 (Intraday Reversal)

근거: 「한국 주식시장의 일중 반전 현상: KOSPI를 중심으로」 (KAIST 석사논문, 2021)
    2011~2020년 KOSPI 종목 고빈도 데이터에서 첫 30분 모멘텀은 없었고,
    장 마감 1시간~30분 전 구간에서 반전(밀린 종목이 되돌아옴)이 확인됨.
    연구들은 대체로 신호 시점에 사서 장 마감까지 보유하는 방식으로 효과를 측정함.

v1 규칙 (2026-11-18 확정)
    종목 범위 : 거래대금 상위 보통주 30개, ETF·ETN·레버리지·인버스 제외 (10분마다 갱신)
    매수 시간 : 14:30 ~ 15:00 동안 계속 감시
    매수 조건 : 오늘 시가 대비 -2% 이하 (-15%보다 많이 빠진 종목 제외)
    고르는 순서: 조건을 만족한 종목 중 시가 대비 가장 많이 떨어진 순
    매도      : 15:15 일괄 매도. 익절·손절 없음 (연구 방식대로 장 마감까지 보유)

v2 (2026-11-20 가상 장부 시작): v1과 같고, 악재 공시가 난 종목만 후보에서 뺀다 (trader/disclosures.py)
    보는 공시  : 직전 거래일 15:30 이후 처음 본 공시 + 그 뒤 오늘까지의 공시
    악재       : 유상증자·전환사채·신주인수권부사채·교환사채 발행, 감자, 횡령·배임, 불성실공시법인,
                 상장적격성, 관리종목, 투자주의환기, 매매거래정지, 회생절차, 파산, 공급계약해지, 영업정지, 소송
    빈자리     : 하락 조건을 만족한 다음 순위 후보로 채움 (v1과 보유 수를 같게 해서 비교를 공정하게)
    감시 종목  : v1과 같은 목록을 같이 씀
"""
import csv
import time
from datetime import datetime
from pathlib import Path

from strategies.base import Strategy
from trader.symbols import is_etf

DATA = Path(__file__).resolve().parent.parent / 'data'
NAN = float('nan')

DROP_PCT = 0.02             # 시가 대비 2% 이상 하락하면 매수 후보
MAX_DROP_PCT = 0.15         # 15% 넘게 빠진 종목은 제외 (악재, 하한가 근처)
TAKE_PROFIT_PCT = None      # 예: 0.02 → 매입가 대비 2% 오르면 매도. None이면 끔 (v1은 끔)
UNIVERSE_SIZE = 30


class CloseReversal(Strategy):
    name = '장 마감 반전'
    VERSION = 'v1'
    buy_window = (-60, -30)     # 마감 60분 전 ~ 30분 전 (평소 14:30 ~ 15:00)
    intraday_exit = TAKE_PROFIT_PCT is not None

    def universe(self, client):
        rows = client.get_trade_value_rank()           # 실패하면 예외 → 실행기가 이전 목록 유지
        stocks = [r for r in rows if not is_etf(r['name'])][:UNIVERSE_SIZE]
        return ({r['code']: (r['name'], 'stock') for r in stocks},
                f'거래대금 상위, ETF 등 {len(rows) - len(stocks)}개 제외')

    def should_buy(self, info, quote):
        if quote['open'] <= 0:
            return None
        change = quote['price'] / quote['open'] - 1
        if -MAX_DROP_PCT < change <= -DROP_PCT:
            return f'시가 {quote["open"]:,} 대비 {change:+.2%}'
        return None

    def pick(self, candidates):
        """시가 대비 가장 많이 떨어진 순"""
        return sorted(candidates, key=lambda c: c[2]['price'] / c[2]['open'])

    def should_sell(self, info, position, quote):
        if TAKE_PROFIT_PCT and quote['price'] >= position['avg_price'] * (1 + TAKE_PROFIT_PCT):
            return f'매입가 대비 +{TAKE_PROFIT_PCT:.0%} 익절'
        return None


class CloseReversalV2(CloseReversal):
    """v1 + 악재 공시 필터"""
    VERSION = 'v2'
    universe_key = 'CloseReversal'      # v1과 같은 감시 종목 목록

    def __init__(self):
        self.reported_bad, self.reported_watch = set(), set()    # 종목별 알림은 하루에 한 번씩만

    def pick(self, candidates):
        from trader.disclosures import scan
        ranked = super().pick(candidates)
        if not ranked:
            return ranked
        bad, watch = scan({c[0] for c in ranked})
        for code, (group, word, title, seen, note) in bad.items():
            if code not in self.reported_bad:
                self.reported_bad.add(code)
                self.notify(f'제외 : {code} 악재 공시 ({group}: {word}) "{title}" 처음 본 시각 {seen[11:16]}'
                            + (f' - {note}' if note else ''))
        for code, (word, title) in watch.items():
            if code not in self.reported_watch:
                self.reported_watch.add(code)
                self.log(f'참고 : {code} 애매한 공시 ({word}) "{title}" - 거르지 않음')
        return [c for c in ranked if c[0] not in bad]


class CloseReversalV3(CloseReversal):
    """v1의 하락 조건 + 업종 괴리율 필터. 종목 범위는 업종별 대장주 바구니 (trader/basket.py)

    v3.0 판단 (2026-11-24 고정, 결과를 보고 바꾸지 않음)
        ① 시가 대비 -2% 이하, -15% 초과 (v1과 같음)
        ② 괴리율 S = R - m 이 -3%p 이하면 제외 (그 종목만의 악재로 봄)
           R = 전일 종가 대비 등락, m = 같은 업종 다른 대장주들의 R 동일 비중 평균 (PEER_TTL초 안에 받은 시세만)
        ③ 같은 업종 시세가 하나도 없으면 ②를 건너뛰고 통과 (비교 불가로 기록)
        고르는 순서는 v1과 같이 시가 대비 가장 많이 떨어진 순
    기록만 (판단에 쓰지 않음, v3.1 후보)
        ④ 미국 동반 하락 예외: 업종 미국 ETF ≤ -2% 이고 m ≤ -2%  ⑤ 저가 근접도 L ≤ 0.3
        간밤 SPY·QQQ·업종 ETF 등락. ⑥ 직전 60분 거래량 비율은 장 마감 뒤 분봉으로 (tools/v3_report.py)
    판단할 때마다 하락 조건을 만족한 후보를 모두 data/<장부>/decisions/YYYYMMDD.csv에 남긴다
    """
    VERSION = 'v3'
    SPREAD_MIN = -0.03
    PEER_TTL = 300
    book = 'paper_close_reversal_v3'    # 실행기가 config의 장부 이름으로 바꿔 끼운다

    def __init__(self):
        self.seen, self.names, self.sector, self.etf = {}, {}, {}, {}
        self.us, self.us_day = {}, None

    def universe(self, client):
        from trader import basket
        b = basket.load()
        if b is None:
            raise RuntimeError('적용할 대장주 바구니가 없습니다 (python -m trader.basket)')
        self.names = dict(zip(b['code'], b['name']))
        self.sector = dict(zip(b['code'], b['sector']))
        self.etf = dict(zip(b['code'], b['us_etf'].fillna('')))
        self.load_us(client)
        return {c: (n, 'stock') for c, n in self.names.items()}, f'업종별 대장주, {b["base"].iloc[0]} 기준'

    def load_us(self, client):
        """간밤 미국 ETF 등락 (하루 한 번). 못 받으면 NaN으로 두고 진행"""
        from trader import basket
        today = datetime.now().strftime('%Y%m%d')
        if self.us_day == today:
            return
        self.us_day, self.us = today, {}
        for sym, exchange in basket.US_EXCHANGE.items():
            try:
                self.us[sym] = client.get_us_change(sym, exchange)
            except Exception as ex:
                self.us[sym] = NAN
                self.log(f'미국 {sym} 등락 조회 실패 : {ex}')

    def should_buy(self, info, quote):
        self.seen[quote['code']] = (time.time(), quote)    # 같은 업종 비교용 (실행기가 감시 종목마다 부른다)
        return super().should_buy(info, quote)

    def pick(self, candidates):
        now, stamp, rows, keep = time.time(), datetime.now().strftime('%H:%M:%S'), [], []
        for code, info, quote, reason in super().pick(candidates):
            sector = self.sector.get(code)
            peers = {c: q for c, (t, q) in self.seen.items()
                     if c != code and self.sector.get(c) == sector and now - t <= self.PEER_TTL}
            r, R = quote['price'] / quote['open'] - 1, quote['rate'] / 100
            m = sum(q['rate'] for q in peers.values()) / 100 / len(peers) if peers else NAN
            s = R - m
            hi, lo = quote['high'], quote['low']
            near = (quote['price'] - lo) / (hi - lo) if hi > lo else 0.0   # 고가 = 저가(점상·점하 등)면 저가와 같다고 봄
            etf = self.etf.get(code, '')
            u = self.us.get(etf, NAN) if etf else NAN
            passed = not peers or s > self.SPREAD_MIN
            why = ('업종 비교 불가' + (', 미국 동반 하락' if u <= -0.02 else '')) if not peers else f'업종 대비 {s:+.1%}'
            rows.append({'time': stamp, 'code': code, 'name': self.names.get(code, code),
                         'sector': sector, 'price': quote['price'], 'open': quote['open'], 'high': hi, 'low': lo,
                         'r_open': round(r, 5), 'r_prev': round(R, 5), 'peers': ' '.join(peers),
                         'peer_mean': round(m, 5), 'spread': round(s, 5), 'passed': int(passed), 'why': why,
                         'near_low': round(near, 3), 'us_etf': etf, 'us_sector': round(u, 5),
                         'us_rescue': int(u <= -0.02 and m <= -0.02), 'spy': round(self.us.get('SPY', NAN), 5),
                         'qqq': round(self.us.get('QQQ', NAN), 5)})
            if passed:
                keep.append((code, info, quote, f'{reason}, {why}'))
        self.write(rows)
        return keep

    def write(self, rows):
        if not rows:
            return
        path = DATA / self.book / 'decisions' / f'{datetime.now():%Y%m%d}.csv'
        path.parent.mkdir(parents=True, exist_ok=True)
        new = not path.exists()
        with open(path, 'a', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            if new:
                w.writeheader()
            w.writerows(rows)

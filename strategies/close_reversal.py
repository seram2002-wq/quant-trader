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
from strategies.base import Strategy
from trader.symbols import is_etf

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

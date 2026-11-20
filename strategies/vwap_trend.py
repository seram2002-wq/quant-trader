"""VWAP 추세 전략

근거: Zarattini, Aziz, "Volume Weighted Average Price (VWAP):
      The Holy Grail for Day Trading Systems" (2023)
    미국 QQQ에서 가격이 VWAP(그날의 거래량 가중 평균가) 위면 매수, 아래면 매도하는
    단순한 규칙이 2018~2023년 수수료 차감 후 샤프 2.1, 최대낙폭 9.4%였다고 보고.
    실무 연구(트레이딩 회사·교육 쪽 저자)이며 미국 시장 결과라 국내에서는 검증이 필요.

국내 적용 (개인은 공매도가 어려워 하락 쪽은 인버스 ETF로 대신함)
    대상      : KODEX 200, KODEX 인버스 (ETF라 매도 세금 없음, 거래량 많음)
    매수      : 종목 가격이 그 종목의 VWAP보다 BAND 이상 위에 있으면 보유
    매도      : VWAP보다 BAND 이상 아래로 내려가면 매도
                (KODEX 200이 VWAP 아래로 가면 보통 인버스는 VWAP 위로 가므로 갈아타게 됨)
    시간      : 09:05 ~ 15:00 판단, 15:15 일괄 매도
    BAND      : VWAP 근처에서 잦은 매매(휩소)를 줄이려고 둔 여유폭. 연구에는 없는 값

v1 규칙 (2026-11-18 시작)
"""
from strategies.base import Strategy

SYMBOLS = {'069500': ('KODEX 200', 'etf'), '114800': ('KODEX 인버스', 'etf')}
BAND = 0.001                # VWAP 위아래 0.1%


class VwapTrend(Strategy):
    name = 'VWAP 추세'
    VERSION = 'v1'
    buy_window = (5, -30)       # 평소 09:05 ~ 15:00
    allow_reentry = True        # 하루에 여러 번 사고팔 수 있음
    intraday_exit = True

    def universe(self, client):
        return dict(SYMBOLS), 'KODEX 200, KODEX 인버스'

    def should_buy(self, info, quote):
        vwap = quote.get('vwap') or 0
        if vwap and quote['price'] > vwap * (1 + BAND):
            return f'현재가 {quote["price"]:,} > VWAP {vwap:,.0f}'
        return None

    def should_sell(self, info, position, quote):
        vwap = quote.get('vwap') or 0
        if vwap and quote['price'] < vwap * (1 - BAND):
            return f'현재가 {quote["price"]:,} < VWAP {vwap:,.0f}'
        return None

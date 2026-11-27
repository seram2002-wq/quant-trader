"""밤사이 보유 (Overnight) — 가상 장부 실험 전략

장 마감 직전에 KODEX 200을 사서 다음 날 장 시작 직후에 판다. 장중에는 들고 있지 않는다.

근거
    한국 시장은 수익의 대부분이 밤사이(전일 종가 → 오늘 시가)에 나고, 장중(시가 → 종가)은
    오히려 마이너스인 경향이 오래 이어졌다. 미국 등 여러 시장에서도 보고된 현상
    (Cliff·Cooper·Gulen 2008 "Return differences between trading and non-trading hours").
    이 저장소의 확인 (results/research_20261118.md)
        코스피 전 종목 시가총액 가중 2011 ~ 2026: 밤사이 연 +21.7% (t 5.77), 장중 연 -12.7% (t -3.52)
        코스피200 지수 2005 ~ 2026: 밤사이 플러스인 해 19/22
        KODEX 200 실제 가격(2023-11 ~ 2026-11): 밤사이 연 +36.9% (같은 기간 지수 +47.0%의 약 4/5)
    회귀로 "효과가 큰 날"을 고르는 방식은 매일 들고 가는 것보다 못해서 매일 같은 규칙으로 한다.

주의 (v0인 이유)
    매일 왕복하므로 비용이 결과를 좌우한다 (왕복 0.01%p 차이가 연 약 2.5%p).
    지수 기준 백테스트는 비용 0.03%에서 탐색 2012 ~ 2019 연 +5.7%, 검증 2020 ~ 2024 연 +12.6%.
    실제 ETF는 효과가 더 작아서 탐색 구간은 채택 기준(코스피 + 5%p)을 못 넘을 수 있다.
    KODEX 200 일봉으로 다시 확인하기 전, 장 마감 반전과 비교하려고 가상 장부에서 먼저 돌린다.

v0 규칙 (2026-11-19 시작)
    대상      : KODEX 200 (069500)
    매수      : 마감 12분 전 ~ 10분 전 (평소 15:18 ~ 15:20), 그때 가격으로
                (실전에서는 장 마감 동시호가 15:20 ~ 15:30에 사는 것이 목표)
    매도      : 다음 날 개장 직후 (평소 09:00. 프로그램을 개장 전에 켜 둘 것)
    자금      : 가상 1,000만 원, 95%
    체결 가정 : 슬리피지 0 (장 마감·장 시작 동시호가 체결을 흉내, config.py의 'slippage': 0.0),
                수수료 0.015%, ETF라 매도 세금 없음
"""
from strategies.base import Strategy

CODE, NAME = '069500', 'KODEX 200'


class OvernightEtf(Strategy):
    name = '밤사이 보유'
    VERSION = 'v0'
    buy_window = (-12, -10)     # 마감 12분 전 ~ 10분 전 (평소 15:18 ~ 15:20)
    intraday_exit = False
    hold_overnight = True
    exit_time = -10             # 일괄 매도 대상이 아님. 마감 10분 전(평소 15:20)에 정리 알림만
    morning_exit = 0            # 다음 날 개장 직후 (평소 09:00, 수능 날 10:00)

    def universe(self, client):
        return {CODE: (NAME, 'etf')}, NAME

    def should_buy(self, info, quote):
        if quote['price'] <= 0:
            return None
        return f'장 마감 전 {quote["price"]:,}원에 매수, 다음 날 시가 매도'


class OvernightEtfV2(OvernightEtf):
    """v0와 같이 장 마감 전에 사고, 다음 날 아침 파는 시점만 전날 밤 SOXX(미국 반도체 ETF)에 따라 바꾼다 — 2026-11-28 시작

    SOXX ≥ 0 : 09:02에 매도 (09:01 봉이 끝난 뒤. 시가 직후 1 ~ 2분 갭 방향으로 더 미는 경향)
    SOXX < 0 : 오늘 시가보다 +1% 오르면 매도, 11:00까지 못 오르면 11:00에 매도
    SOXX를 못 받으면 v0처럼 바로 매도. 근거: docs/backtest_summary.md 23절 (2025-12 ~ 2026-11 아침 1분봉, 봉인 구간,
    SOXX ≥ 0인 141일 09:01 봉 종가 +0.12%p, SOXX < 0인 97일 +1% 반등 +0.41%p, 0.9 ~ 1.1%가 고르게 좋음).
    shortcut: 실전은 지금 가격이 +1%에 닿는 순간 팔아서 백테스트(1분봉 종가 기준)보다 조금 일찍 팔림,
              미국 휴장 다음 날은 그 전 미국 장 등락으로 판단 (날짜를 안 봄)
    """
    VERSION = 'v2'
    UP = 0.01                   # SOXX가 빠진 날, 시가 대비 이만큼 오르면 판다
    WAIT_UP, DEADLINE = 2, 120  # 개장 뒤 분: SOXX가 오른 날 매도 시각(09:02), 빠진 날 마지막 시각(11:00)

    def __init__(self):
        self.soxx_day, self.soxx = None, None

    def morning_reason(self, client, quote, t, default):
        from datetime import datetime

        from trader import market
        today = datetime.now().strftime('%Y%m%d')
        if self.soxx_day != today:
            self.soxx_day = today
            try:
                self.soxx = client.get_us_change('SOXX', 'NAS')
                self.log(f'전날 밤 SOXX {self.soxx:+.2%}')
            except Exception as ex:                  # 미국 시세가 없어도 아침 매도는 해야 함
                self.soxx = None
                self.log(f'SOXX 조회 실패, 시가에 바로 매도 ({ex})')
        if self.soxx is None:
            return default + ' (SOXX 조회 실패)'
        if self.soxx >= 0:
            return f'전날 밤 SOXX {self.soxx:+.2%} → {market.at(self.WAIT_UP) // 100}:{market.at(self.WAIT_UP) % 100:02d} 매도' \
                if t >= market.at(self.WAIT_UP) else None
        if quote['open'] and quote['price'] >= quote['open'] * (1 + self.UP):
            return f'전날 밤 SOXX {self.soxx:+.2%} → 시가 {quote["open"]:,} 대비 +{self.UP:.0%} 반등 매도'
        if t >= market.at(self.DEADLINE):
            return f'전날 밤 SOXX {self.soxx:+.2%} → {market.at(self.DEADLINE) // 100}:{market.at(self.DEADLINE) % 100:02d}까지 +{self.UP:.0%} 못 올라 매도'
        return None

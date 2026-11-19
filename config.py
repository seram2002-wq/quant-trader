"""공통 설정

비밀 값(키, 토큰, 계좌번호)은 .env에 두고, 여기에는 숫자와 목록만 둔다.
"""

# ---------------------------------------------------------------- 실행할 전략
# strategy : strategies 폴더의 '파일이름.클래스이름'
# account  : 'mock' (모의투자 계좌에 실제 주문) 또는 'paper' (가상 장부)
# capital  : 이 전략이 쓰는 자금. 모의투자 계좌에 더 많은 돈이 있어도 이만큼만 쓴다
# budget   : 종목당 쓸 비율 (capital 기준)
# max_positions : 동시에 보유할 최대 종목 수
# channel  : 슬랙 채널을 적어 둔 .env 항목 이름
# 장부는 data/<account>_<파일이름>/ 에, 보고서는 results/<account>_<파일이름>.md 에 따로 생긴다.
#
# 운영 방식
#   모의투자 = 운영 후보. 지금 가장 믿을 만한 로직 하나만 둔다 (실전으로 옮길 로직)
#   가상 장부 = 실험실. 새 전략과 변형을 돌린다
#   그림자 장부 = 모의투자 로직을 가상 장부에서도 똑같이 돌린 것.
#                 같은 로직의 모의투자와 가상 결과 차이로 가상 장부가 얼마나 낙관적인지 재고,
#                 실험 전략은 이 그림자 장부와 비교한다
STRATEGIES = [
    # 운영 후보: 모의투자 계좌에 실제 주문
    {'strategy': 'close_reversal.CloseReversal', 'account': 'mock',
     'capital': 10_000_000, 'budget': 0.24, 'max_positions': 4,
     'channel': 'MOCK_SLACK_CHANNEL'},
    # 그림자: 위와 같은 로직을 가상 장부에서
    {'strategy': 'close_reversal.CloseReversal', 'account': 'paper',
     'capital': 10_000_000, 'budget': 0.24, 'max_positions': 4,
     'channel': 'PAPER_SLACK_CHANNEL'},
    # 실험: 밤사이 보유 (15:18 KODEX 200 매수, 다음 날 09:00 매도). ETF라 슬리피지를 작게
    {'strategy': 'overnight_etf.OvernightEtf', 'account': 'paper',
     'capital': 10_000_000, 'budget': 0.95, 'max_positions': 1,
     'channel': 'PAPER_SLACK_CHANNEL', 'slippage': 0.0001},
    # 실험: 멀티팩터 (15:05 종목 교체, 다음 날까지 보유)
    # 2026-11-18 백테스트에서 기준(연 10%)을 못 넘어 보류
    # {'strategy': 'multi_factor.MultiFactor', 'account': 'paper',
    #  'capital': 10_000_000, 'budget': 0.19, 'max_positions': 5,
    #  'channel': 'PAPER_SLACK_CHANNEL'},
    # 실험 전략은 여기에 'account': 'paper'로 추가 (예: VWAP 추세)
    # {'strategy': 'vwap_trend.VwapTrend', 'account': 'paper',
    #  'capital': 10_000_000, 'budget': 0.95, 'max_positions': 1,
    #  'channel': 'PAPER_SLACK_CHANNEL'},
]

# 전략이 종목을 직접 고르지 않을 때 쓰는 목록 (변동성 돌파 전략 등)
SYMBOLS = {
    '069500': ('KODEX 200', 'etf'),
    '229200': ('KODEX 코스닥150', 'etf'),
    '114800': ('KODEX 인버스', 'etf'),
    '251340': ('KODEX 코스닥150선물인버스', 'etf'),
}

# ---------------------------------------------------------------- 체결 비용 (가상 체결과 손익 추정)
# 실제와 비슷하게 하려고 넣는 값이며, 실제 수수료와 세율은 실전 전에 확인할 것
FEE_RATE = 0.00015              # 매수, 매도 수수료 (0.015%)
SLIPPAGE = 0.0005               # 가상 체결 가격 차이: 매수 0.05% 비싸게, 매도 0.05% 싸게
STOCK_SELL_TAX = 0.0020         # 일반 주식 매도 세금 (ETF는 0)

# ---------------------------------------------------------------- 시간표 (HHMM)
START_TIME = 905                # 이 시각부터 판단 (전략별 매수 시간은 전략 파일의 buy_window)
EXIT_TIME = 1515                # 이 시각에 보유 종목 일괄 매도 (다음 날까지 보유하는 전략은 제외)
STOP_TIME = 1520                # 이 시각 이후 종료
REPORT_MINUTE = 30              # 매시 이 분에 전략별 잔고 알림

# ---------------------------------------------------------------- 조회
LOOP_SLEEP = 5                  # 한 바퀴 다 본 뒤 쉬는 시간(초)
QUOTE_TTL = 3                   # 같은 종목 현재가를 이 시간(초) 안에는 다시 조회하지 않고 같이 씀
UNIVERSE_REFRESH = 600          # 감시 종목을 다시 고르는 간격(초)

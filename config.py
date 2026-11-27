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
    # 실험: 장 마감 반전 v2 = v1 + 악재 공시 필터. 장부 이름을 따로 줘서 그림자(v1)와 나란히
    {'strategy': 'close_reversal.CloseReversalV2', 'account': 'paper', 'book': 'paper_close_reversal_v2',
     'capital': 10_000_000, 'budget': 0.24, 'max_positions': 4,
     'channel': 'PAPER_SLACK_CHANNEL'},
    # 실험: 장 마감 반전 v3 = 업종별 대장주 바구니 + 업종 괴리율 필터 (2026-11-25 시작, 3개월·거른 사례 20건 뒤 판정)
    # order 1: 바구니 36종목 시세 조회가 모의투자 판단을 늦추지 않게 모의투자 다음에 돈다
    {'strategy': 'close_reversal.CloseReversalV3', 'account': 'paper', 'book': 'paper_close_reversal_v3',
     'capital': 10_000_000, 'budget': 0.24, 'max_positions': 4,
     'channel': 'PAPER_SLACK_CHANNEL', 'order': 1},
    # 실험: 밤사이 보유 (15:18 KODEX 200 매수, 다음 날 09:00 매도). 2026-11-20부터 2 ~ 3주만 참고로.
    # 슬리피지 0 = 장 마감·장 시작 동시호가 체결을 흉내 (왕복 비용 = 수수료 0.015% × 2)
    {'strategy': 'overnight_etf.OvernightEtf', 'account': 'paper',
     'capital': 10_000_000, 'budget': 0.95, 'max_positions': 1,
     'channel': 'PAPER_SLACK_CHANNEL', 'slippage': 0.0},
    # 실험: 밤사이 보유 v2 (같이 사고, 아침 매도만 전날 밤 SOXX에 따라: ≥0이면 09:02, <0이면 시가 +1% 반등 또는 11:00). 11-30 시작
    {'strategy': 'overnight_etf.OvernightEtfV2', 'account': 'paper', 'book': 'paper_overnight_etf_v2',
     'capital': 10_000_000, 'budget': 0.95, 'max_positions': 1,
     'channel': 'PAPER_SLACK_CHANNEL', 'slippage': 0.0},
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

# ---------------------------------------------------------------- 업종별 대장주 바구니 (trader/basket.py)
# 산업 분류(KSIC)로는 업종을 잘못 잡는 종목만 이름으로 직접 지정 (삼성전자는 KSIC상 '통신 및 방송 장비')
SECTOR_OVERRIDE = {'삼성전자': '반도체'}
# 산업 분류가 사업회사로 잡혀 자동으로 안 걸러지는 지주사 (이름). '기타 금융업'의 비금융 지주사는 규칙으로 빠짐
HOLDING_EXCLUDE_LIST = ['두산', 'CJ', 'GS', '한화', '원익홀딩스', '에코프로']

# ---------------------------------------------------------------- 체결 비용 (가상 체결과 손익 추정)
# 실제와 비슷하게 하려고 넣는 값이며, 실제 수수료와 세율은 실전 전에 확인할 것
FEE_RATE = 0.00015              # 매수, 매도 수수료 (0.015%)
SLIPPAGE = 0.0005               # 가상 체결 가격 차이: 매수 0.05% 비싸게, 매도 0.05% 싸게
STOCK_SELL_TAX = 0.0020         # 일반 주식 매도 세금 (ETF는 0)

# ---------------------------------------------------------------- 시간표
# 장 시간 기준 분 (trader/market.py): 0 이상 = 개장 N분 뒤, 음수 = 마감 N분 전.
# 장 시간이 다른 날(수능 등)은 SPECIAL_HOURS에 그날만 적으면 매수·매도·종료·분봉 저장 시각이 같이 밀린다.
MARKET_HOURS = (900, 1530)      # 평소 (개장, 마감) HHMM
SPECIAL_HOURS = {               # 'YYYYMMDD': (개장, 마감). 거래소 공지를 보고 미리 적어 둘 것
    '20261119': (1000, 1630),   # 2027학년도 수능
}
# 평일 휴장일: run.py가 켜져도 바로 끝낸다 (작업 스케줄러가 평일마다 켜므로). 거래소 휴장일 공지를 보고 미리 적어 둘 것
HOLIDAYS = {
    '20261225',                 # 성탄절
    '20261231',                 # 연말 휴장
    # 2027년: 거래소 공식 공고(보통 12월 말) 전에 법정 공휴일·대체공휴일로 적은 것. 공고가 나오면 맞춰 볼 것.
    # 빠뜨리면 휴장일에 가짜 매매가 생기고, 더 넣으면 하루 쉬는 것뿐이라 애매한 날(?)도 넣어 둠
    '20270101',                 # 신정
    '20270205', '20270208',     # 설 연휴 (설날 2/6 토), 일요일과 겹친 대체공휴일 2/8
    '20270301',                 # 삼일절
    '20270503',                 # 노동절(5/1 토) 대체공휴일 (?)
    '20270505',                 # 어린이날
    '20270513',                 # 부처님오신날
    '20270719',                 # 제헌절(7/17 토) 대체공휴일 (?, 2026년 공휴일 재지정)
    '20270816',                 # 광복절(8/15 일) 대체공휴일
    '20270914', '20270915', '20270916',   # 추석 연휴
    '20271004',                 # 개천절(10/3 일) 대체공휴일
    '20271011',                 # 한글날(10/9 토) 대체공휴일
    '20271227',                 # 성탄절(12/25 토) 대체공휴일
    '20271231',                 # 연말 휴장
}
START_TIME = 5                  # 개장 5분 뒤부터 판단 (전략별 매수 시간은 전략 파일의 buy_window)
EXIT_TIME = -15                 # 마감 15분 전 보유 종목 일괄 매도 (다음 날까지 보유하는 전략은 제외)
STOP_TIME = -10                 # 마감 10분 전 이후 종료
REPORT_MINUTE = 30              # 매시 이 분에 전략별 잔고 알림

# ---------------------------------------------------------------- 조회
LOOP_SLEEP = 5                  # 한 바퀴 다 본 뒤 쉬는 시간(초)
QUOTE_TTL = 3                   # 같은 종목 현재가를 이 시간(초) 안에는 다시 조회하지 않고 같이 씀
UNIVERSE_REFRESH = 600          # 감시 종목을 다시 고르는 간격(초)
# 뉴스 판정 그림자 기록 (run.py NewsCheck). 2026-11-20 끔: 네이버 검색 API 약관(2026-09-07 시행)이
# 검색 결과 장기 저장·평가 활용을 금지하는지 원문(developers.naver.com/notice/article/33400)으로 확인한 뒤 켤 것
NEWS_SHADOW = False

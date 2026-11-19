"""전략의 기본 틀

새 전략은 이 클래스를 상속해서 필요한 메서드만 채운다.
실행기(run.py)가 정해진 시간표에 맞춰 이 메서드들을 부른다.

quote(현재가 정보)에는 price, open, high, low, rate(전일 대비 %), volume, value(거래대금),
vwap(오늘의 거래량 가중 평균가)이 들어 있다.
"""


class Strategy:
    name = '기본 전략'
    VERSION = 'v1'              # 규칙을 바꾸면 올린다. 매매 기록과 보고서에 남는다
    buy_window = (905, 1515)    # 매수 판단을 하는 시간 (HHMM, 시작 포함, 끝 미포함)
    allow_reentry = False       # 같은 날 판 종목을 다시 살 수 있는지
    intraday_exit = True        # 장중 매도 조건이 있는지 (없으면 보유 종목을 계속 조회하지 않음)
    rebalance_time = None       # HHMM. 정하면 should_buy 대신 하루 한 번 이 시각에 targets()로 종목을 교체
    hold_overnight = False      # True면 15:15 일괄 매도를 하지 않고 다음 날까지 보유
    exit_time = None            # HHMM. 이 전략의 장 마감 정리 시각 (None이면 config.EXIT_TIME)
    morning_exit = None         # HHMM. 정하면 전날 산 종목을 다음 날 이 시각에 모두 판다

    def universe(self, client):
        """감시할 종목 {code: (name, kind)}와 설명 문자열. 기본은 config.SYMBOLS

        조회에 실패하면 예외를 일으킨다. 실행기는 이전 목록을 계속 쓴다.
        """
        import config
        return dict(config.SYMBOLS), 'config.SYMBOLS'

    def prepare(self, client, code, today):
        """하루에 한 번, 종목별로 판단에 필요한 값을 계산해 딕셔너리로 돌려준다.

        계산할 수 없으면(오늘 시세 없음 등) None. today: 'YYYYMMDD'
        """
        return {}

    def should_buy(self, info, quote):
        """매수 신호면 매수 이유(문자열), 아니면 None"""
        return None

    def pick(self, candidates):
        """매수 후보 중 무엇을 어떤 순서로 살지 정한다.

        candidates: [(code, info, quote, reason)] - should_buy가 이유를 돌려준 종목들
        기본은 감시 순서 그대로. 순위를 매기고 싶은 전략은 이 메서드를 바꾼다.
        """
        return candidates

    def should_sell(self, info, position, quote):
        """장중 매도 신호면 매도 이유(문자열), 아니면 None

        position: {'qty', 'avg_price', 'cost', 'high'(매수 후 최고가), 'time', 'name', 'kind'}
        15:15 일괄 매도는 실행기가 따로 처리한다.
        """
        return None

    def describe(self, info):
        """로그에 남길 종목별 설명"""
        return str(info) if info else ''

    def targets(self, client, holdings, max_positions):
        """종목 교체 전략(rebalance_time)만 쓴다. 들고 갈 종목 목록과 보고 문자열

        holdings: 지금 보유 종목 {code: position}
        돌려주는 목록: [{'code', 'name', 'kind', 'reason'}]. 목록에 없는 보유 종목은 매도된다.
        """
        return [], ''
